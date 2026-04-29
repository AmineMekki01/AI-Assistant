class JarvisAudioProcessor extends AudioWorkletProcessor {
  constructor() {
    super()
    this._buffer = []
    this._frameSize = 4096

    this.port.onmessage = (event) => {
      const data = event.data
      if (!data || typeof data !== 'object') {
        return
      }

      if (data.type === 'flush') {
        this._flush()
        this.port.postMessage({ type: 'flushed' })
      }
    }
  }

  _flush() {
    if (this._buffer.length === 0) {
      return
    }

    const totalLength = this._buffer.reduce((sum, chunk) => sum + chunk.length, 0)
    const merged = new Float32Array(totalLength)
    let offset = 0

    for (const chunk of this._buffer) {
      merged.set(chunk, offset)
      offset += chunk.length
    }

    this._buffer = []
    this.port.postMessage(merged, [merged.buffer])
  }

  process(inputs) {
    const input = inputs[0]
    const channel = input && input[0]

    if (!channel || channel.length === 0) {
      return true
    }

    this._buffer.push(new Float32Array(channel))

    const bufferedLength = this._buffer.reduce((sum, chunk) => sum + chunk.length, 0)
    if (bufferedLength >= this._frameSize) {
      this._flush()
    }

    return true
  }
}

registerProcessor('jarvis-audio-processor', JarvisAudioProcessor)
