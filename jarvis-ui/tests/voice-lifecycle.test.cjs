const { test } = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const vm = require('node:vm')
const ts = require('typescript')

function hookHarness(file, name, globals = {}, args = []) {
  const slots = [], effects = []
  let cursor = 0
  const same = (a, b) => a && b && a.length === b.length && a.every((x, i) => Object.is(x, b[i]))
  const react = {
    useState(initial) {
      const i = cursor++
      if (!slots[i]) slots[i] = { value: initial }
      return [slots[i].value, value => { slots[i].value = typeof value === 'function' ? value(slots[i].value) : value }]
    },
    useRef(value) {
      const i = cursor++
      return slots[i] ||= { current: value }
    },
    useCallback(fn, deps) {
      const i = cursor++
      if (!slots[i] || !same(slots[i].deps, deps)) slots[i] = { fn, deps }
      return slots[i].fn
    },
    useEffect(fn, deps) {
      const i = cursor++
      if (!slots[i] || !same(slots[i].deps, deps)) {
        slots[i]?.cleanup?.()
        slots[i] = { fn, deps }
        effects.push(() => { slots[i].cleanup = fn() })
      }
    }
  }
  const code = ts.transpileModule(fs.readFileSync(file, 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 }
  }).outputText
  const context = { exports: {}, require: n => { assert.equal(n, 'react'); return react },
    console, setTimeout, clearTimeout, Float32Array, Uint8Array, ArrayBuffer, Blob, TextDecoder, btoa, ...globals }
  vm.runInNewContext(code, context, { filename: file })
  return {
    render() { cursor = 0; const value = context.exports[name](...args); effects.splice(0).forEach(fn => fn()); return value },
    cleanup() { slots.forEach(slot => slot?.cleanup?.()) }
  }
}

class Socket {
  static OPEN = 1
  static instances = []
  readyState = 0
  bufferedAmount = 0
  sent = []
  constructor() { Socket.instances.push(this) }
  send(payload) { this.sent.push(JSON.parse(payload)) }
  close() { this.readyState = 3 }
  open() { this.readyState = 1; this.onopen() }
}

test('streamed caption keeps its identity when a late user transcript arrives', async () => {
  Socket.instances = []
  const h = hookHarness('src/hooks/useWebSocket.ts', 'useWebSocket', { WebSocket: Socket }, ['ws://test'])
  h.render()
  const socket = Socket.instances[0]
  socket.open()
  for (const message of [
    { type: 'message', id: 'r1', role: 'assistant', text: 'Hello' },
    { type: 'message', role: 'user', text: 'Hi' },
    { type: 'message', id: 'r1', role: 'assistant', text: 'Hello there' },
    { type: 'message', id: 'r2', role: 'assistant', text: 'Next reply' }
  ]) await socket.onmessage({ data: JSON.stringify(message) })
  const messages = h.render().messages
  assert.equal(messages.length, 3)
  assert.equal(messages[0].text, 'Hello there')
  assert.equal(messages[2].id, 'r2')
  const draft = { type: 'mail_draft', account: 'gmail', to: 'test@example.com', subject: 'test', body: 'test', rawText: 'test' }
  await socket.onmessage({ data: JSON.stringify(draft) })
  assert.ok(h.render().pendingMailDraft)
  await socket.onmessage({ data: JSON.stringify({ ...draft, cleared: true }) })
  assert.equal(h.render().pendingMailDraft, null)
  h.cleanup()
})

test('disconnected microphone audio and commands are never replayed', () => {
  Socket.instances = []
  const h = hookHarness('src/hooks/useWebSocket.ts', 'useWebSocket', { WebSocket: Socket }, ['ws://test'])
  const hook = h.render(), socket = Socket.instances[0]
  hook.sendAudioChunk(new Float32Array([0.5]))
  assert.equal(hook.send({ type: 'confirm_mail_draft' }), false)
  socket.open()
  assert.equal(socket.sent.length, 0)
  hook.sendAudioChunk(new Float32Array([0.5]))
  assert.equal(socket.sent.length, 1)
  socket.bufferedAmount = 200000
  hook.sendAudioChunk(new Float32Array([0.5]))
  assert.equal(socket.sent.length, 1)
  h.cleanup()
})

test('reconnect clears speaking state and ignores old socket events', async () => {
  Socket.instances = []
  const timers = []
  const h = hookHarness('src/hooks/useWebSocket.ts', 'useWebSocket', {
    WebSocket: Socket, setTimeout: fn => { timers.push(fn); return timers.length }, clearTimeout: () => {}
  }, ['ws://test'])
  h.render()
  const old = Socket.instances[0]
  old.open()
  await old.onmessage({ data: JSON.stringify({ type: 'speaking', isSpeaking: true }) })
  assert.equal(h.render().isSpeaking, true)
  old.close(); old.onclose()
  assert.equal(h.render().isSpeaking, false)
  timers.shift()()
  const next = Socket.instances[1]
  next.open()
  old.onclose()
  await old.onmessage({ data: JSON.stringify({ type: 'speaking', isSpeaking: true }) })
  assert.equal(h.render().isSpeaking, false)
  assert.equal(h.render().setRecording(true), true)
  assert.equal(next.sent[0].type, 'set_recording')
  h.cleanup()
})

test('stopping while microphone permission is pending releases the late stream', async () => {
  let grant
  let stopped = 0
  const h = hookHarness('src/hooks/useAudio.ts', 'useAudio', {
    navigator: { mediaDevices: { getUserMedia: () => new Promise(resolve => { grant = resolve }) } },
    document: { addEventListener() {}, removeEventListener() {} }, cancelAnimationFrame() {}
  })
  const hook = h.render()
  const pending = hook.startRecording()
  await hook.stopRecording()
  grant({ getTracks: () => [{ stop() { stopped++ } }] })
  assert.equal(await pending, false)
  assert.equal(stopped, 1)
  assert.equal(h.render().isRecording, false)
  h.cleanup()
})

test('permission denial is reported without leaving recording active', async () => {
  const h = hookHarness('src/hooks/useAudio.ts', 'useAudio', {
    navigator: { mediaDevices: { getUserMedia: async () => { throw new Error('permission denied') } } },
    document: { addEventListener() {}, removeEventListener() {} }, cancelAnimationFrame() {}
  })
  assert.equal(await h.render().startRecording(), false)
  assert.equal(h.render().isRecording, false)
  assert.ok(h.render().error)
  h.cleanup()
})

test('audio worklet flush emits the final partial frame before acknowledgement', () => {
  const sent = []
  let Processor
  vm.runInNewContext(fs.readFileSync('public/audio-processor.js', 'utf8'), {
    AudioWorkletProcessor: class { port = { postMessage: message => sent.push(message) } },
    Float32Array, registerProcessor: (_, cls) => { Processor = cls }
  })
  const processor = new Processor()
  for (let i = 0; i < 10; i++) processor.process([[new Float32Array(128).fill(0.25)]])
  assert.equal(sent[0].length, 1024)
  processor.port.onmessage({ data: { type: 'flush' } })
  assert.equal(sent[1].length, 256)
  assert.equal(sent[2].type, 'flushed')
})
