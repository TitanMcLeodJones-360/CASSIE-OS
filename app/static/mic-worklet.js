/* Convert hot-mic input into short, bounded speech clips in the browser. */
class CassieMic extends AudioWorkletProcessor {
    constructor() {
        super();
        this.block = new Int16Array(800);
        this.noise = .003;
        this.phase = 0;
        this.sum = 0;
        this.count = 0;
        this.manual = null;
        this.meterTick = 0;
        this.reset();
        this.port.onmessage = event => {
            const {paused, record} = event.data;
            if (record === false) {
                if (this.manual) {
                    if (this.used) this.manual.push(this.block.slice(0, this.used));
                    if (this.manual.length) this.emit(this.manual, true);
                    else this.port.postMessage({empty: true});
                }
                this.manual = null;
            } else if (record === true) {
                this.manual = [];
            } else {
                this.paused = paused;
                this.manual = null;
            }
            this.reset();
        };
    }

    reset() {
        this.used = 0;
        this.power = 0;
        this.lead = [];
        this.clip = [];
        this.quiet = 0;
        this.voiced = 0;
    }

    emit(parts, manual) {
        const clip = new Int16Array(parts.reduce((total, part) => total + part.length, 0));
        let offset = 0;
        for (const part of parts) {
            clip.set(part, offset);
            offset += part.length;
        }
        this.port.postMessage({clip: clip.buffer, manual}, [clip.buffer]);
    }

    finishBlock() {
        const level = Math.sqrt(this.power / this.block.length);
        if (this.meterTick++ % 2 === 0) this.port.postMessage({level});
        const loud = level > Math.max(.0035, this.noise * 2.6);
        const part = this.block.slice();
        if (this.manual) {
            this.manual.push(part);
            if (this.manual.length >= 200) {
                this.emit(this.manual, true);
                this.manual = null;
                this.reset();
            }
        } else if (this.clip.length) {
            this.clip.push(part);
            this.quiet = loud ? 0 : this.quiet + 1;
            this.voiced += Number(loud);
            if (this.quiet >= 10 || this.clip.length >= 210) {
                if (this.voiced >= 2) this.emit(this.clip, false);
                this.reset();
            }
        } else {
            this.lead.push(part);
            if (this.lead.length > 5) this.lead.shift();
            if (loud) {
                this.clip = this.lead;
                this.voiced = 1;
            } else {
                this.noise = this.noise * .96 + level * .04;
            }
        }
        this.used = 0;
        this.power = 0;
    }

    process(inputs) {
        if (this.paused) return true;
        for (const sample of inputs[0]?.[0] || []) {
            this.phase += 16_000;
            this.sum += sample;
            this.count++;
            if (this.phase < sampleRate) continue;
            const value = this.sum / this.count;
            this.sum = this.count = 0;
            do {
                this.phase -= sampleRate;
                this.power += value * value;
                this.block[this.used++] = Math.round(Math.max(-1, Math.min(1, value)) * 32767);
                if (this.used === this.block.length) this.finishBlock();
            } while (this.phase >= sampleRate);
        }
        return true;
    }
}

registerProcessor('cassie-mic', CassieMic);
