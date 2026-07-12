using System;
using System.Reflection;
using HarmonyLib;
using UnityEngine;

namespace CRPGBridge.Hooks
{
    /// <summary>
    /// Central gate for whether the agent's injected input is currently driving
    /// the game. The lockdown guards below refuse dangerous engine paths (quit to
    /// menu, quit game, run a console command, open the console/in-game menu)
    /// whenever the agent is active, so a random policy can never cheat via the
    /// console or kill the bridge by quitting mid-episode.
    ///
    /// AgentActive is true exactly when input is being injected AND no scripted
    /// config window is open. The env opens a config window (build application,
    /// level-up, revive) to legitimately mutate state — during that window the
    /// agent is not stepping, so mutation is permitted. BridgeBypass lets the env
    /// itself drive LoadMainMenu / Application.Quit (to_menu / shutdown).
    /// </summary>
    public static class Lockdown
    {
        // Set true while the scripted config window is open (build/level-up/revive).
        public static volatile bool ConfigWindowOpen;

        // Set true transiently while the ENV itself initiates a menu/quit.
        public static volatile bool BridgeBypass;

        // The agent is "active" (and thus locked down) only while it is actually
        // injecting input and no scripted config window is open.
        public static bool AgentActive
        {
            get { return InputInjector.Active && !ConfigWindowOpen; }
        }
    }

    /// <summary>
    /// Installs the Harmony guards that enforce <see cref="Lockdown"/>. Same
    /// prefix-returns-false-to-skip pattern as TelemetrySafety/CreationSafety.
    /// </summary>
    public static class LockdownGuards
    {
        public static Action<string> Log = delegate { };

        public static void Install(Harmony harmony)
        {
            // Exit-to-menu sink: covers the in-game menu "Main Menu" button and the
            // death-screen "Quit" button (both funnel through here). Blocked during
            // agent play unless the env set BridgeBypass (to_menu/shutdown).
            Guard(harmony, "Game.GameState", "LoadMainMenu", new[] { typeof(bool) }, nameof(GateBypass));

            // Console execution sink: both the in-game UICommandLine.OnSubmit and the
            // mod's own HandleConsole route through SDK.CommandLine.RunCommand. During
            // agent play there is no config window open, so this is refused; inside a
            // config window AgentActive is false and the mod's console still runs.
            Guard(harmony, "SDK.CommandLine", "RunCommand", new[] { typeof(string) }, nameof(GateBypass));

            // Quit-game sink. May be an internal call on some Unity builds; tolerate
            // an un-patchable target (UIInGameMenu.Show suppression already blocks the
            // only agent-reachable path to it).
            GuardType(harmony, typeof(Application), "Quit", Type.EmptyTypes, nameof(GateBypass));

            // Defense-in-depth: never let the console box or the in-game menu open
            // while the agent is active, even if some future path tried to.
            Guard(harmony, "UICommandLine", "Activate", new[] { typeof(bool) }, nameof(GateAgentOnly));
            Guard(harmony, "UIInGameMenu", "Show", Type.EmptyTypes, nameof(GateAgentOnly));
        }

        // ---- guard installation helpers -------------------------------------

        private static void Guard(Harmony harmony, string typeName, string method, Type[] sig, string prefixName)
        {
            var t = AccessTools.TypeByName(typeName);
            if (t == null) { Log("type not found: " + typeName); return; }
            GuardType(harmony, t, method, sig, prefixName);
        }

        private static void GuardType(Harmony harmony, Type t, string method, Type[] sig, string prefixName)
        {
            try
            {
                MethodInfo m = sig.Length == 0 && t == typeof(Application)
                    ? AccessTools.Method(t, method, Type.EmptyTypes)
                    : AccessTools.Method(t, method, sig);
                if (m == null) { Log("method not found: " + t.Name + "." + method); return; }
                var prefix = new HarmonyMethod(typeof(LockdownGuards).GetMethod(
                    prefixName, BindingFlags.NonPublic | BindingFlags.Static));
                harmony.Patch(m, prefix: prefix);
                Log("guarded " + t.Name + "." + method);
            }
            catch (Exception ex)
            {
                Log("guard FAILED " + t.Name + "." + method + ": " + ex.Message);
            }
        }

        // ---- prefixes (return false to skip the original) -------------------

        // Refuse when the agent is active and the env did not request a bypass.
        private static bool GateBypass()
        {
            return !(Lockdown.AgentActive && !Lockdown.BridgeBypass);
        }

        // Refuse whenever the agent is active (env never needs these paths).
        private static bool GateAgentOnly()
        {
            return !Lockdown.AgentActive;
        }
    }
}
