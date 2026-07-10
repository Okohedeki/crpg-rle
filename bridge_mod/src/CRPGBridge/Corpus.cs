using System.Collections.Generic;
using System.IO;
using Newtonsoft.Json.Linq;

namespace CRPGBridge
{
    /// <summary>
    /// Loads the frozen paraphrase corpus (corpus.json) produced by the offline
    /// pipeline. Maps "conv:node" -> list of paraphrase variants. The interceptor
    /// picks a variant deterministically from the episode seed.
    /// </summary>
    public sealed class Corpus
    {
        private readonly Dictionary<string, string[]> _variants = new Dictionary<string, string[]>();
        public string Version = "";
        public bool Loaded;

        public static string Key(string conv, int node)
        {
            return conv.ToLowerInvariant() + ":" + node;
        }

        public bool Load(string path)
        {
            _variants.Clear();
            Loaded = false;
            if (!File.Exists(path)) return false;

            JObject root = JObject.Parse(File.ReadAllText(path));
            Version = root["version"] != null ? root["version"].Value<string>() : "";
            var options = root["options"] as JObject;
            if (options == null) return false;

            foreach (var kv in options)
            {
                var variantsTok = kv.Value["variants"] as JArray;
                if (variantsTok == null) continue;
                var list = new List<string>();
                foreach (var v in variantsTok) list.Add(v.Value<string>());
                if (list.Count > 0) _variants[kv.Key.ToLowerInvariant()] = list.ToArray();
            }
            Loaded = true;
            return true;
        }

        /// <summary>Returns the chosen paraphrase for (conv, node) given the
        /// episode seed, or null if this option has no variants.</summary>
        public string PickVariant(string conv, int node, ulong seed)
        {
            string[] variants;
            if (!_variants.TryGetValue(Key(conv, node), out variants) || variants.Length == 0)
                return null;
            ulong stream = seed ^ SplitMix64.Hash64(conv.ToLowerInvariant()) ^ (ulong)node;
            var rng = new SplitMix64(stream);
            int idx = (int)(rng.NextU64() % (ulong)variants.Length);
            return variants[idx];
        }

        public int Count { get { return _variants.Count; } }
    }
}
