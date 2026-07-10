namespace CRPGBridge
{
    /// <summary>
    /// SplitMix64 + FNV-1a hash, byte-for-byte identical to crpg_rle.core.rng
    /// (Python). The dialogue randomizer derives the same variant pick and
    /// option-order permutation on both sides from (seed, conv, node), so the
    /// C# mod's swap/shuffle matches what Python expects. Cross-language golden
    /// vectors pin the two together.
    /// </summary>
    public sealed class SplitMix64
    {
        private ulong _state;

        public SplitMix64(ulong seed) { _state = seed; }

        public ulong NextU64()
        {
            unchecked
            {
                _state += 0x9E3779B97F4A7C15UL;
                ulong z = _state;
                z = (z ^ (z >> 30)) * 0xBF58476D1CE4E5B9UL;
                z = (z ^ (z >> 27)) * 0x94D049BB133111EBUL;
                return z ^ (z >> 31);
            }
        }

        /// <summary>In-place Fisher-Yates identical to the Python shuffle()
        /// (iterate i high→low, j = next % (i+1)).</summary>
        public void Shuffle<T>(System.Collections.Generic.IList<T> list)
        {
            for (int i = list.Count - 1; i > 0; i--)
            {
                int j = (int)(NextU64() % (ulong)(i + 1));
                T tmp = list[i];
                list[i] = list[j];
                list[j] = tmp;
            }
        }

        public static ulong Hash64(string text)
        {
            unchecked
            {
                ulong h = 0xCBF29CE484222325UL;
                byte[] bytes = System.Text.Encoding.UTF8.GetBytes(text);
                foreach (byte b in bytes)
                {
                    h = (h ^ b) * 0x100000001B3UL;
                }
                return h;
            }
        }
    }
}
