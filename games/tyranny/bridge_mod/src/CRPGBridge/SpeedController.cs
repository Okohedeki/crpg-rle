using UnityEngine;

namespace CRPGBridge
{
    /// <summary>
    /// Controls faster-than-real-time stepping. TimeController.Flash(x) sets an
    /// arbitrary time multiplier (the same path the game's own Flash cheat uses);
    /// UpdateTimeScale() re-asserts it every frame, so we just re-issue Flash when
    /// our target changes. Movement is frame-rate coupled, so uncapping fps is what
    /// actually makes multipliers above ~1.8x take effect.
    /// </summary>
    public static class SpeedController
    {
        private static float _target = 1.0f;

        public static void SetTimeScale(float multiplier)
        {
            _target = Mathf.Max(0.01f, multiplier);
            var tc = TimeController.Instance;
            if (tc != null) tc.Flash(_target);
        }

        public static void UncapFps(bool uncap)
        {
            if (uncap)
            {
                QualitySettings.vSyncCount = 0;
                Application.targetFrameRate = -1;
            }
        }

        /// <summary>Re-assert the target each frame; the engine's UpdateTimeScale
        /// otherwise resets the scale (e.g. after combat end).</summary>
        public static void Tick()
        {
            if (_target == 1.0f) return;
            var tc = TimeController.Instance;
            if (tc != null && !TimeControllerPaused(tc))
            {
                if (!Mathf.Approximately(Time.timeScale, _target))
                    tc.Flash(_target);
            }
        }

        private static bool TimeControllerPaused(TimeController tc)
        {
            return tc.Paused;
        }

        public static float Target { get { return _target; } }
    }
}
