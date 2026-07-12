using System.Reflection;
using HarmonyLib;

namespace CRPGBridge.Hooks
{
    /// <summary>
    /// The game's TelemetryManager can NRE when the env drives flows (e.g.
    /// character-creation completion) outside the normal menu boot that would
    /// have initialized it. Telemetry is irrelevant to the environment, so we
    /// prefix every Game.TelemetryManager.QueueEvent_* to a no-op. This keeps
    /// creation completion (and anything else emitting telemetry) from crashing.
    /// </summary>
    public static class TelemetrySafety
    {
        public static System.Action<string> Log = delegate { };

        public static void Install(Harmony harmony)
        {
            var t = AccessTools.TypeByName("Game.TelemetryManager");
            if (t == null) { Log("Game.TelemetryManager not found"); return; }
            var skip = new HarmonyMethod(typeof(TelemetrySafety).GetMethod(
                nameof(Skip), BindingFlags.NonPublic | BindingFlags.Static));
            int patched = 0;
            foreach (MethodInfo m in t.GetMethods(BindingFlags.Public | BindingFlags.Instance | BindingFlags.Static))
            {
                if (m.Name.StartsWith("QueueEvent") && !m.IsAbstract && !m.ContainsGenericParameters)
                {
                    try { harmony.Patch(m, prefix: skip); patched++; }
                    catch { /* skip un-patchable overloads */ }
                }
            }
            Log("neutralized " + patched + " TelemetryManager.QueueEvent* methods");
        }

        // Returning false skips the original method body.
        private static bool Skip() { return false; }
    }
}
