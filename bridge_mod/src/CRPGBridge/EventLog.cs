using System.Collections.Generic;
using Newtonsoft.Json.Linq;
using UnityEngine;

namespace CRPGBridge
{
    /// <summary>
    /// Frame-stamped event buffer fed by the Harmony hooks and drained into
    /// each observe response. Cap guards against unbounded growth if the
    /// client stops polling.
    /// </summary>
    public static class EventLog
    {
        private const int Cap = 4096;
        private static readonly object _gate = new object();
        private static readonly List<JObject> _events = new List<JObject>();
        private static int _dropped;

        public static void Add(string type, JObject data)
        {
            JObject e = data ?? new JObject();
            e["type"] = type;
            e["frame"] = Time.frameCount;
            lock (_gate)
            {
                if (_events.Count < Cap) _events.Add(e);
                else _dropped++;
            }
        }

        public static JArray Drain()
        {
            lock (_gate)
            {
                var arr = new JArray();
                foreach (JObject e in _events) arr.Add(e);
                if (_dropped > 0)
                {
                    arr.Add(new JObject { ["type"] = "events_dropped", ["count"] = _dropped });
                    _dropped = 0;
                }
                _events.Clear();
                return arr;
            }
        }
    }
}
