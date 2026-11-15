PROB_BITS = 11
PROB_TOTAL = 1 << PROB_BITS
PROB_INIT = PROB_TOTAL >> 1
MOVE_BITS = 5
TOP = 1 << 24
MASK32 = 0xFFFFFFFF


class Encoder:
    __slots__ = ("low", "range", "cache", "cache_size", "out")

    def __init__(self):
        self.low = 0
        self.range = MASK32
        self.cache = 0
        self.cache_size = 1
        self.out = bytearray()

    def _shift_low(self):
        low = self.low
        if low < 0xFF000000 or low > MASK32:
            carry = low >> 32
            self.out.append((self.cache + carry) & 0xFF)
            n = self.cache_size - 1
            if n:
                self.out.extend(bytes([(0xFF + carry) & 0xFF]) * n)
            self.cache = (low >> 24) & 0xFF
            self.cache_size = 0
        self.cache_size += 1
        self.low = ((low & MASK32) << 8) & MASK32

    def encode(self, probs, idx, bit):
        p = probs[idx]
        bound = (self.range >> PROB_BITS) * p
        if bit:
            self.low += bound
            self.range -= bound
            probs[idx] = p - (p >> MOVE_BITS)
        else:
            self.range = bound
            probs[idx] = p + ((PROB_TOTAL - p) >> MOVE_BITS)
        while self.range < TOP:
            self.range <<= 8
            self._shift_low()

    def flush(self):
        for _ in range(5):
            self._shift_low()
        return bytes(self.out)


class Decoder:
    __slots__ = ("data", "pos", "range", "code", "length")

    def __init__(self, data):
        self.data = data
        self.length = len(data)
        self.pos = 0
        self.range = MASK32
        self.code = 0
        for _ in range(5):
            self.code = ((self.code << 8) | self._byte()) & MASK32

    def _byte(self):
        p = self.pos
        self.pos = p + 1
        if p < self.length:
            return self.data[p]
        return 0

    def decode(self, probs, idx):
        p = probs[idx]
        bound = (self.range >> PROB_BITS) * p
        if self.code < bound:
            self.range = bound
            probs[idx] = p + ((PROB_TOTAL - p) >> MOVE_BITS)
            bit = 0
        else:
            self.code -= bound
            self.range -= bound
            probs[idx] = p - (p >> MOVE_BITS)
            bit = 1
        while self.range < TOP:
            self.range <<= 8
            self.code = ((self.code << 8) | self._byte()) & MASK32
        return bit


def enc_tree(encoder, probs, base, bits, value):
    node = 1
    for i in range(bits - 1, -1, -1):
        bit = (value >> i) & 1
        encoder.encode(probs, base + node, bit)
        node = (node << 1) | bit


def dec_tree(decoder, probs, base, bits):
    node = 1
    for _ in range(bits):
        node = (node << 1) | decoder.decode(probs, base + node)
    return node - (1 << bits)


def enc_bits(encoder, probs, base, count, value):
    for i in range(count - 1, -1, -1):
        bit = (value >> i) & 1
        encoder.encode(probs, base + i, bit)


def dec_bits(decoder, probs, base, count):
    value = 0
    for i in range(count - 1, -1, -1):
        value |= decoder.decode(probs, base + i) << i
    return value
