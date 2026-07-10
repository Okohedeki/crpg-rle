using System.Reflection;
using HarmonyLib;

namespace CRPGBridge.Hooks
{
    /// <summary>
    /// When creation is completed via a template (skipping Conquest), Conquest map
    /// objects still get enabled and NRE in ApplyReputationColor because their
    /// reputation refs were never set up — this freezes the completion on a black
    /// screen. Neutralize that method (cosmetic map coloring) so completion can
    /// proceed. Same pattern as TelemetrySafety.
    /// </summary>
    public static class CreationSafety
    {
        public static System.Action<string> Log = delegate { };

        public static void Install(Harmony harmony)
        {
            var t = AccessTools.TypeByName("Game.ConquestLocation");
            if (t == null) { Log("Game.ConquestLocation not found"); return; }
            var skip = new HarmonyMethod(typeof(CreationSafety).GetMethod(
                nameof(Skip), BindingFlags.NonPublic | BindingFlags.Static));
            int n = 0;
            foreach (string name in new[] { "ApplyReputationColor" })
            {
                var m = AccessTools.Method(t, name);
                if (m != null) { try { harmony.Patch(m, prefix: skip); n++; } catch { } }
            }
            Log("neutralized " + n + " ConquestLocation method(s)");
        }

        private static bool Skip() { return false; }
    }
}
