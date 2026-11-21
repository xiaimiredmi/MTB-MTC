// Loader for the WebAssembly build of the codec.
//
// The module is plain `#[no_mangle] extern "C"`, no bindgen: buffers go into
// linear memory, results come back as a pointer and a length. Every read of
// `memory.buffer` happens after the call that might have grown it, because a
// grown memory detaches the old view — the classic way this goes wrong.

const WASM = "mtc.wasm";

export async function loadCodec(url = WASM) {
  // Fetch + instantiate by hand rather than instantiateStreaming: a plain static
  // server may serve .wasm as application/octet-stream, which the streaming API
  // rejects.
  const response = await fetch(url);
  if (!response.ok) throw new Error(`无法加载 ${url}（${response.status}）`);
  const bytes = await response.arrayBuffer();
  const { instance } = await WebAssembly.instantiate(bytes, {});
  const e = instance.exports;
  const memory = e.memory;

  const view = (ptr, len) => new Uint8Array(memory.buffer, ptr, len);

  return {
    version: e.mtc_version(),

    /** Encode pixels; `data` is RGBA (4 channels) or grey/RGB (1/3). */
    encode({ data, width, height, channels, quality, lossless = false, aq = false }) {
      const len = data.length;
      const src = e.mtc_alloc(len);
      view(src, len).set(data);
      const t0 = performance.now();
      const outLen = e.mtc_encode(
        src, len, width, height, channels, quality,
        lossless ? 1 : 0, aq ? 1 : 0,
      );
      const ms = performance.now() - t0;
      e.mtc_free(src, len);
      if (!outLen) throw new Error("编码失败");
      const ptr = e.mtc_out_ptr();
      return { bytes: view(ptr, outLen).slice(), ms };
    },

    /** Decode `.mtc` bytes; `maxSide` > 0 decodes straight to a smaller picture. */
    decode(bytes, maxSide = 0) {
      const src = e.mtc_alloc(bytes.length);
      view(src, bytes.length).set(bytes);
      const t0 = performance.now();
      const outLen = e.mtc_decode(src, bytes.length, maxSide);
      const ms = performance.now() - t0;
      e.mtc_free(src, bytes.length);
      if (!outLen) throw new Error("解码失败：不是有效的 .mtc，或这个构建读不了它");
      const ptr = e.mtc_out_ptr();
      const rgba = view(ptr, outLen).slice();
      return { rgba, width: e.mtc_out_w(), height: e.mtc_out_h(), ms };
    },
  };
}

/** Parse the 12-byte container header, the same way docs/FORMAT.md describes. */
export function parseHeader(bytes) {
  if (bytes.length < 12) return null;
  const magic = String.fromCharCode(bytes[0], bytes[1], bytes[2], bytes[3]);
  if (magic !== "MTB1") return null;
  const view = new DataView(bytes.buffer, bytes.byteOffset, 12);
  const modes = [
    "gray-lossy", "rgb444-lossy", "rgb420-lossy",
    "gray-lossless", "rgb-lossless",
  ];
  return {
    magic,
    version: bytes[4],
    mode: bytes[5],
    modeName: modes[bytes[5]] || `mode ${bytes[5]}`,
    quality: bytes[6],
    flags: bytes[7],
    hasAlpha: (bytes[7] & 1) !== 0,
    hasAq: (bytes[7] & 2) !== 0,
    width: view.getUint16(8, true),
    height: view.getUint16(10, true),
  };
}

/** Hex dump of the first `n` bytes. */
export function hexDump(bytes, n = 12) {
  return Array.from(bytes.slice(0, n))
    .map((b) => b.toString(16).toUpperCase().padStart(2, "0"))
    .join(" ");
}

/** PSNR over the channels the format actually stores, skipping invisible pixels. */
export function psnr(a, b, width, height) {
  let se = 0;
  let count = 0;
  for (let i = 0; i < width * height; i++) {
    const o = i * 4;
    const alphaA = a[o + 3];
    const alphaB = b[o + 3];
    // The codec zeroes the colour of pixels below the transparency threshold on
    // purpose, so scoring those against the source would measure the rule.
    if (alphaA < 8 || alphaB < 8) continue;
    for (let c = 0; c < 3; c++) {
      const d = a[o + c] - b[o + c];
      se += d * d;
      count++;
    }
  }
  if (!count) return 99;
  const mse = se / count;
  if (mse <= 0) return 99;
  return 10 * Math.log10((255 * 255) / mse);
}

export function humanBytes(n) {
  if (n >= 1024 * 1024) return (n / 1048576).toFixed(2) + " MB";
  if (n >= 1024) return (n / 1024).toFixed(1) + " KB";
  return n + " B";
}
