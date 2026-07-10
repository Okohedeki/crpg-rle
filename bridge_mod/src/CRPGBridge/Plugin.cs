using System;
using BepInEx;
using HarmonyLib;
using Newtonsoft.Json.Linq;
using UnityEngine;

namespace CRPGBridge
{
    [BepInPlugin(PluginGuid, PluginName, PluginVersion)]
    public class Plugin : BaseUnityPlugin
    {
        public const string PluginGuid = "com.crpgrle.bridge";
        public const string PluginName = "CRPG Bridge";
        public const string PluginVersion = "0.1.0";
        public const int ProtocolVersion = 1;

        private IpcServer _ipc;
        private Harmony _harmony;

        private void Awake()
        {
            int instanceId = ParseIntEnv("CRPG_INSTANCE_ID", 0);
            int port = ParseIntEnv("CRPG_BRIDGE_PORT", 5555 + instanceId);

            _harmony = new Harmony(PluginGuid);
            InputInjector.Log = s => Logger.LogWarning("[input] " + s);
            InputInjector.Apply(_harmony);
            Logger.LogInfo(string.Format("[input] icall patches: {0} ok, {1} failed",
                InputInjector.PatchedOk.Count, InputInjector.PatchFailed.Count));

            Hooks.EventHooks.Log = s => Logger.LogInfo("[events] " + s);
            Hooks.EventHooks.Install(_harmony);

            _ipc = new IpcServer(port);
            _ipc.Log = s => Logger.LogInfo("[ipc] " + s);
            _ipc.Register("handshake", HandleHandshake);
            _ipc.Register("ping", req => new JObject());
            _ipc.Register("shutdown", HandleShutdown);
            _ipc.Register("input", HandleInputMode);
            _ipc.Register("act", HandleAct);
            _ipc.Register("diag_input", HandleDiagInput);
            _ipc.Register("observe", req => new JObject
            {
                ["state"] = StateReader.Snapshot(),
                ["events"] = EventLog.Drain()
            });
            _ipc.Register("load", HandleLoad);
            _ipc.Register("console", HandleConsole);
            _ipc.Start();

            Logger.LogInfo(string.Format(
                "{0} v{1} loaded. Unity {2}, instance {3}, IPC listening on 127.0.0.1:{4}",
                PluginName, PluginVersion, Application.unityVersion, instanceId, port));
        }

        private void Update()
        {
            Hooks.EventHooks.Tick();
            if (_ipc != null) _ipc.Pump();
        }

        private JObject HandleHandshake(JObject req)
        {
            return new JObject
            {
                ["proto"] = ProtocolVersion,
                ["plugin"] = PluginVersion,
                ["unity"] = Application.unityVersion,
                ["product"] = Application.productName
            };
        }

        private JObject HandleShutdown(JObject req)
        {
            Application.Quit();
            return new JObject();
        }

        private JObject HandleInputMode(JObject req)
        {
            bool on = req["active"] != null && req["active"].Value<bool>();
            InputInjector.Active = on;
            if (!on) InputInjector.ClearAll();
            return new JObject { ["active"] = InputInjector.Active };
        }

        private int _actEndFrame = -1;

        /// <summary>
        /// act: {inputs: [{t:"cursor",x,y} | {t:"button",btn:"left|right|middle",action:"press|down|up"}
        ///               | {t:"key",key:"<KeyCode>",action:"press|down|up"}], frames: k}
        /// Schedules the inputs, then defers the response until k frames have rendered.
        /// </summary>
        private JObject HandleAct(JObject req)
        {
            if (_actEndFrame < 0)
            {
                InputInjector.Active = true;
                var inputs = req["inputs"] as JArray;
                if (inputs != null)
                {
                    foreach (JToken tok in inputs) ScheduleInput((JObject)tok);
                }
                int frames = req["frames"] != null ? req["frames"].Value<int>() : 1;
                _actEndFrame = Time.frameCount + Math.Max(1, frames);
                return null; // defer
            }

            if (Time.frameCount < _actEndFrame) return null; // still waiting

            _actEndFrame = -1;
            return new JObject { ["frame"] = Time.frameCount };
        }

        private static void ScheduleInput(JObject input)
        {
            string t = input["t"].Value<string>();
            switch (t)
            {
                case "cursor":
                    InputInjector.SetCursor(input["x"].Value<float>(), input["y"].Value<float>());
                    break;
                case "button":
                {
                    string btnName = input["btn"].Value<string>();
                    int btn = btnName == "right" ? 1 : btnName == "middle" ? 2 : 0;
                    string action = input["action"] != null ? input["action"].Value<string>() : "press";
                    if (action == "press") InputInjector.PressButton(btn);
                    else InputInjector.HoldButton(btn, action == "down");
                    break;
                }
                case "key":
                {
                    var key = (KeyCode)Enum.Parse(typeof(KeyCode), input["key"].Value<string>(), true);
                    string action = input["action"] != null ? input["action"].Value<string>() : "press";
                    if (action == "press") InputInjector.PressKey(key);
                    else InputInjector.HoldKey(key, action == "down");
                    break;
                }
                default:
                    throw new ArgumentException("unknown input type: " + t);
            }
        }

        /// <summary>load: {file: "name.savegame"} — starts an async in-engine load.
        /// Completion = observe.loading falling edge.</summary>
        private JObject HandleLoad(JObject req)
        {
            string file = req["file"].Value<string>();
            bool accepted = Game.GameResources.LoadGame(file);
            return new JObject { ["accepted"] = accepted };
        }

        /// <summary>console: {cmd: "..."} — debug/test lever; enables cheats on first use.</summary>
        private JObject HandleConsole(JObject req)
        {
            SDK.GameState.CheatsEnabled = true;
            SDK.CommandLine.RunCommand(req["cmd"].Value<string>());
            return new JObject();
        }

        private JObject HandleDiagInput(JObject req)
        {
            Vector3 raw = Input.mousePosition;          // goes through the icall patch when active
            Vector3 viaGameInput = GameInput.MousePosition; // engine's own wrapper (firstpass)
            return new JObject
            {
                ["active"] = InputInjector.Active,
                ["patched"] = new JArray(InputInjector.PatchedOk.ToArray()),
                ["failed"] = new JArray(InputInjector.PatchFailed.ToArray()),
                ["mouse_raw"] = new JArray(raw.x, raw.y),
                ["mouse_gameinput"] = new JArray(viaGameInput.x, viaGameInput.y),
                ["screen"] = new JArray(Screen.width, Screen.height)
            };
        }

        private void OnDestroy()
        {
            // Should only fire at application exit. If it appears at startup, the
            // engine swept the plugin object again — requires BepInEx.cfg
            // HideManagerGameObject = true (the engine destroys unknown root objects).
            Logger.LogWarning("plugin object destroyed — IPC going down");
            if (_ipc != null) _ipc.Dispose();
        }

        private static int ParseIntEnv(string name, int fallback)
        {
            string raw = Environment.GetEnvironmentVariable(name);
            int value;
            if (raw != null && int.TryParse(raw, out value)) return value;
            return fallback;
        }
    }
}
