using System;
using System.Collections.Generic;
using System.Reflection;
using HarmonyLib;
using UnityEngine;

namespace CRPGBridge
{
    /// <summary>
    /// Virtual player-input layer. Harmony-prefixes the UnityEngine.Input icalls so that,
    /// while active, BOTH input consumers in this engine — GameInput (world/conversation)
    /// and NGUI's UICamera (menus, character creation), which each read UnityEngine.Input
    /// directly — see the injected cursor/button/key state instead of real hardware.
    /// Unmodified game logic decodes the virtual input exactly as it would a human's.
    ///
    /// Edge semantics follow Unity's: a "down"/"up" edge lasts exactly one rendered frame.
    /// Scheduling is keyed on Time.frameCount and advanced lazily from the patch bodies,
    /// so it is independent of script-execution order.
    /// </summary>
    public static class InputInjector
    {
        public static bool Active;

        // Current virtual state (screen px, Unity convention: origin bottom-left).
        private static Vector3 _mousePos = new Vector3(100f, 100f, 0f);
        private static readonly bool[] _btnHeld = new bool[3];
        private static readonly bool[] _btnDown = new bool[3];
        private static readonly bool[] _btnUp = new bool[3];
        private static readonly HashSet<KeyCode> _keyHeld = new HashSet<KeyCode>();
        private static readonly HashSet<KeyCode> _keyDown = new HashSet<KeyCode>();
        private static readonly HashSet<KeyCode> _keyUp = new HashSet<KeyCode>();

        // Frame-keyed schedule of state transitions.
        private class Transition
        {
            public int Frame;
            public Action Apply;
        }

        private static readonly List<Transition> _schedule = new List<Transition>();
        private static int _lastSeenFrame = -1;

        public static readonly List<string> PatchedOk = new List<string>();
        public static readonly List<string> PatchFailed = new List<string>();

        public static Action<string> Log = delegate { };

        // ------------------------------------------------------------------ schedule

        /// <summary>Applies due transitions and clears one-frame edges. Safe to call often.</summary>
        private static void Advance()
        {
            int frame = Time.frameCount;
            if (frame == _lastSeenFrame) return;
            _lastSeenFrame = frame;

            // New frame: previous frame's edges expire.
            for (int i = 0; i < 3; i++) { _btnDown[i] = false; _btnUp[i] = false; }
            _keyDown.Clear();
            _keyUp.Clear();

            for (int i = _schedule.Count - 1; i >= 0; i--)
            {
                if (_schedule[i].Frame <= frame)
                {
                    _schedule[i].Apply();
                    _schedule.RemoveAt(i);
                }
            }
        }

        private static void At(int frame, Action apply)
        {
            _schedule.Add(new Transition { Frame = frame, Apply = apply });
        }

        public static void SetCursor(float xNorm, float yNorm)
        {
            _mousePos = new Vector3(
                Mathf.Clamp01(xNorm) * Screen.width,
                Mathf.Clamp01(yNorm) * Screen.height,
                0f);
        }

        /// <summary>Queue a full press (down this frame+1, up the frame after).</summary>
        public static void PressButton(int button)
        {
            int f = Time.frameCount;
            At(f + 1, () => { _btnDown[button] = true; _btnHeld[button] = true; });
            At(f + 2, () => { _btnUp[button] = true; _btnHeld[button] = false; });
        }

        public static void HoldButton(int button, bool held)
        {
            int f = Time.frameCount;
            if (held) At(f + 1, () => { _btnDown[button] = true; _btnHeld[button] = true; });
            else At(f + 1, () => { _btnUp[button] = true; _btnHeld[button] = false; });
        }

        public static void PressKey(KeyCode key)
        {
            int f = Time.frameCount;
            At(f + 1, () => { _keyDown.Add(key); _keyHeld.Add(key); });
            At(f + 2, () => { _keyUp.Add(key); _keyHeld.Remove(key); });
        }

        public static void HoldKey(KeyCode key, bool held)
        {
            int f = Time.frameCount;
            if (held) At(f + 1, () => { _keyDown.Add(key); _keyHeld.Add(key); });
            else At(f + 1, () => { _keyUp.Add(key); _keyHeld.Remove(key); });
        }

        public static void ClearAll()
        {
            _schedule.Clear();
            for (int i = 0; i < 3; i++) { _btnHeld[i] = false; _btnDown[i] = false; _btnUp[i] = false; }
            _keyHeld.Clear(); _keyDown.Clear(); _keyUp.Clear();
        }

        // ------------------------------------------------------------------ patches

        public static void Apply(Harmony harmony)
        {
            Type input = typeof(Input);
            Type self = typeof(InputInjector);

            TryPatch(harmony, AccessTools.PropertyGetter(input, "mousePosition"), self, "PreMousePosition");
            TryPatch(harmony, AccessTools.Method(input, "GetMouseButton", new[] { typeof(int) }), self, "PreGetMouseButton");
            TryPatch(harmony, AccessTools.Method(input, "GetMouseButtonDown", new[] { typeof(int) }), self, "PreGetMouseButtonDown");
            TryPatch(harmony, AccessTools.Method(input, "GetMouseButtonUp", new[] { typeof(int) }), self, "PreGetMouseButtonUp");
            TryPatch(harmony, AccessTools.Method(input, "GetKey", new[] { typeof(KeyCode) }), self, "PreGetKey");
            TryPatch(harmony, AccessTools.Method(input, "GetKeyDown", new[] { typeof(KeyCode) }), self, "PreGetKeyDown");
            TryPatch(harmony, AccessTools.Method(input, "GetKeyUp", new[] { typeof(KeyCode) }), self, "PreGetKeyUp");
            TryPatch(harmony, AccessTools.Method(input, "GetAxis", new[] { typeof(string) }), self, "PreGetAxis");
            TryPatch(harmony, AccessTools.Method(input, "GetAxisRaw", new[] { typeof(string) }), self, "PreGetAxis");
        }

        private static void TryPatch(Harmony harmony, MethodBase target, Type self, string prefixName)
        {
            string label = target == null ? prefixName + " (target missing)" : target.Name;
            try
            {
                if (target == null) throw new MissingMethodException(prefixName);
                harmony.Patch(target, prefix: new HarmonyMethod(self.GetMethod(prefixName, BindingFlags.NonPublic | BindingFlags.Static)));
                PatchedOk.Add(label);
            }
            catch (Exception ex)
            {
                PatchFailed.Add(label + ": " + ex.GetType().Name + ": " + ex.Message);
                Log("input patch FAILED for " + label + ": " + ex.Message);
            }
        }

        private static bool PreMousePosition(ref Vector3 __result)
        {
            if (!Active) return true;
            Advance();
            __result = _mousePos;
            return false;
        }

        private static bool PreGetMouseButton(int button, ref bool __result)
        {
            if (!Active) return true;
            Advance();
            __result = button >= 0 && button < 3 && _btnHeld[button];
            return false;
        }

        private static bool PreGetMouseButtonDown(int button, ref bool __result)
        {
            if (!Active) return true;
            Advance();
            __result = button >= 0 && button < 3 && _btnDown[button];
            return false;
        }

        private static bool PreGetMouseButtonUp(int button, ref bool __result)
        {
            if (!Active) return true;
            Advance();
            __result = button >= 0 && button < 3 && _btnUp[button];
            return false;
        }

        private static bool PreGetKey(KeyCode key, ref bool __result)
        {
            if (!Active) return true;
            Advance();
            __result = _keyHeld.Contains(key);
            return false;
        }

        private static bool PreGetKeyDown(KeyCode key, ref bool __result)
        {
            if (!Active) return true;
            Advance();
            __result = _keyDown.Contains(key);
            return false;
        }

        private static bool PreGetKeyUp(KeyCode key, ref bool __result)
        {
            if (!Active) return true;
            Advance();
            __result = _keyUp.Contains(key);
            return false;
        }

        private static bool PreGetAxis(string axisName, ref float __result)
        {
            if (!Active) return true;
            // Mask real mouse/scroll deltas while virtual input is driving.
            __result = 0f;
            return false;
        }
    }
}
