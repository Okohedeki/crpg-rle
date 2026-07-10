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

            DialogueInterceptor.Log = s => Logger.LogInfo("[dialogue] " + s);
            DialogueInterceptor.Apply(_harmony);

            Hooks.TelemetrySafety.Log = s => Logger.LogInfo("[telemetry] " + s);
            Hooks.TelemetrySafety.Install(_harmony);

            Hooks.CreationSafety.Log = s => Logger.LogInfo("[creationsafety] " + s);
            Hooks.CreationSafety.Install(_harmony);

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
            _ipc.Register("diag_asm", HandleDiagAsm);
            _ipc.Register("start_conv", HandleStartConv);
            _ipc.Register("speed", HandleSpeed);
            _ipc.Register("new_game", HandleNewGame);
            _ipc.Register("to_menu", HandleToMenu);
            _ipc.Register("dialogue", HandleDialogue);
            _ipc.Register("creation", HandleCreation);
            _ipc.Register("diag_creation_ui", HandleDiagCreationUi);
            _ipc.Register("creation_options", req => CreationChoices.ListOptions());
            _ipc.Register("creation_choose", req => CreationChoices.Choose(req["index"].Value<int>()));
            _ipc.Register("diag_rng", HandleDiagRng);
            _ipc.Register("diag_dialogue", HandleDiagDialogue);
            _ipc.Start();

            Logger.LogInfo(string.Format(
                "{0} v{1} loaded. Unity {2}, instance {3}, IPC listening on 127.0.0.1:{4}",
                PluginName, PluginVersion, Application.unityVersion, instanceId, port));
        }

        private void Update()
        {
            Hooks.EventHooks.Tick();
            SpeedController.Tick();
            if (_ipc != null) _ipc.Pump();
        }

        private JObject HandleSpeed(JObject req)
        {
            if (req["time_scale"] != null) SpeedController.SetTimeScale(req["time_scale"].Value<float>());
            if (req["uncap_fps"] != null) SpeedController.UncapFps(req["uncap_fps"].Value<bool>());
            return new JObject { ["time_scale"] = SpeedController.Target };
        }

        /// <summary>new_game: start a fresh playthrough into character creation
        /// (LifePath scene). Agent then drives creation via input.</summary>
        private JObject HandleNewGame(JObject req)
        {
            if (Game.GameState.Instance != null)
                Game.GameState.Instance.PlaythroughGUID = System.Guid.NewGuid();
            SDK.GameState.NewGame = true;
            UnityEngine.SceneManagement.SceneManager.LoadScene("LifePath",
                UnityEngine.SceneManagement.LoadSceneMode.Single);
            return new JObject { ["started"] = true };
        }

        /// <summary>to_menu: return to the main menu (for a mid-episode reset).</summary>
        private JObject HandleToMenu(JObject req)
        {
            Game.GameState.LoadMainMenu(false);
            return new JObject();
        }

        /// <summary>creation: {action: "advance"|"regress"|"complete"|"set_name", name?}.
        /// Scripts the character-creation wizard navigation (the env's job); the agent
        /// makes the actual choices within each stage via cursor+click. Returns the
        /// current stage and readiness so the driver knows when it can complete.</summary>
        private JObject HandleCreation(JObject req)
        {
            var mgr = UICharacterCreationManager.Instance;
            if (mgr == null) return new JObject { ["ok"] = false, ["error"] = "not in creation" };
            string action = req["action"] != null ? req["action"].Value<string>() : "";
            switch (action)
            {
                // PressOkay/PressBack are the validated Next/Back the real UI buttons
                // use (they gate on valid stage choices); AdvanceStage is a naive counter.
                case "advance": mgr.PressOkay(); break;
                case "regress": mgr.PressBack(); break;
                case "begin_conquest": mgr.BeginConquest(); break;
                case "quick_start": QuickStartTemplate(mgr, req["name"] != null ? req["name"].Value<string>() : "Agent"); break;
                case "set_name": SetCreationName(mgr, req["name"] != null ? req["name"].Value<string>() : "Agent"); break;
                case "complete":
                    if (!mgr.IsCharacterCreationReadyForCompletion())
                        return new JObject { ["ok"] = false, ["error"] = "not ready for completion" };
                    // Scripted completion via reflection does not cleanly transition
                    // (bypassing normal boot leaves character/Conquest infra half-init).
                    // The reliable infrastructure path is loading a pre-made Act-1-start
                    // save (start_mode="act1_save"); see docs/DOD.md. Left as-is for when
                    // the real-UI-driven creation flow is scripted.
                    mgr.HandleCharacterCreationComplete();
                    break;
                case "":
                    break;
                default:
                    return new JObject { ["ok"] = false, ["error"] = "unknown creation action: " + action };
            }
            bool ready;
            try { ready = mgr.IsCharacterCreationReadyForCompletion(); } catch { ready = false; }
            return new JObject { ["stage"] = mgr.CurrentStage, ["last_stage"] = mgr.LastStage, ["ready"] = ready };
        }

        private static void SetCreationName(UICharacterCreationManager mgr, string name)
        {
            // The build character info lives at mgr.RootController.Character.Name; reach it
            // by reflection to avoid coupling to the nested type.
            try
            {
                var rootController = mgr.GetType().GetField("RootController",
                    System.Reflection.BindingFlags.Public | System.Reflection.BindingFlags.Instance);
                object controller = rootController != null ? rootController.GetValue(mgr) : null;
                if (controller == null) return;
                var charProp = controller.GetType().GetField("Character",
                    System.Reflection.BindingFlags.Public | System.Reflection.BindingFlags.Instance);
                object character = charProp != null ? charProp.GetValue(controller) : null;
                if (character == null) return;
                var nameField = character.GetType().GetField("Name",
                    System.Reflection.BindingFlags.Public | System.Reflection.BindingFlags.Instance);
                if (nameField != null) nameField.SetValue(character, name);
            }
            catch { }
        }

        // Deterministic fresh character: pick a pre-made background template
        // (skips Conquest) so IsCharacterCreationReadyForCompletion can pass
        // without a trained agent. Used by start_mode="creation_quickstart".
        private static void QuickStartTemplate(UICharacterCreationManager mgr, string name)
        {
            try
            {
                object character = mgr.PaperdollCharacterInfo;
                // BackgroundMode = Template
                var bgField = character.GetType().GetField("BackgroundMode",
                    System.Reflection.BindingFlags.Public | System.Reflection.BindingFlags.Instance);
                var options = mgr.HistoryOptions;
                var templatesField = options != null ? options.GetType().GetField("Templates",
                    System.Reflection.BindingFlags.Public | System.Reflection.BindingFlags.Instance) : null;
                var templates = templatesField != null ? templatesField.GetValue(options) as Array : null;
                if (templates != null && templates.Length > 0 && bgField != null)
                {
                    // BackgroundMode enum value "Template" == 1 (Conquest == 0).
                    bgField.SetValue(character, Enum.ToObject(bgField.FieldType, 1));
                    var htProp = character.GetType().GetProperty("HistoryTemplate",
                        System.Reflection.BindingFlags.Public | System.Reflection.BindingFlags.Instance);
                    if (htProp != null) htProp.SetValue(character, templates.GetValue(0), null);
                }
                SetCreationName(mgr, name);
            }
            catch (Exception ex) { }
        }

        /// <summary>diag_creation_ui: skills state + on-screen positions of skill
        /// increment widgets, so a test can click one and confirm it registers.</summary>
        private JObject HandleDiagCreationUi(JObject req)
        {
            var result = new JObject { ["in_creation"] = false };
            var mgr = UICharacterCreationManager.Instance;
            if (mgr == null) return result;
            result["in_creation"] = true;
            result["stage"] = mgr.CurrentStage;

            object character = mgr.PaperdollCharacterInfo;
            try
            {
                var sptProp = character.GetType().GetProperty("SkillPointsToSpend");
                if (sptProp != null) result["skill_points_to_spend"] = (int)sptProp.GetValue(character, null);
                var deltasField = character.GetType().GetField("SkillValueDeltas");
                if (deltasField != null)
                {
                    var deltas = deltasField.GetValue(character) as int[];
                    if (deltas != null)
                    {
                        var arr = new JArray();
                        foreach (int d in deltas) arr.Add(d);
                        result["skill_deltas"] = arr;
                    }
                }
            }
            catch { }

            // Find on-screen skill increment widgets.
            var widgets = new JArray();
            Camera cam = Camera.main;
            var setters = UnityEngine.Object.FindObjectsOfType<UICharacterCreationSkillSetter>();
            foreach (var setter in setters)
            {
                if (!setter.gameObject.activeInHierarchy) continue;
                int adj = 0;
                try { var f = setter.GetType().GetField("Adjustment"); if (f != null) adj = (int)f.GetValue(setter); } catch { }
                Vector3 wp = setter.transform.position;
                Camera c = cam != null ? cam : Camera.current;
                Vector3 sp = c != null ? c.WorldToScreenPoint(wp) : new Vector3(-1, -1, 0);
                widgets.Add(new JObject
                {
                    ["adjustment"] = adj,
                    ["skill"] = setter.Skill.ToString(),
                    ["x"] = sp.x / Screen.width,
                    ["y"] = sp.y / Screen.height,
                    ["on_screen"] = sp.z > 0 && sp.x >= 0 && sp.x <= Screen.width && sp.y >= 0 && sp.y <= Screen.height
                });
            }
            result["skill_widgets"] = widgets;
            return result;
        }

        /// <summary>dialogue: {active, seed, corpus_path?} — arm the per-episode
        /// randomizer (paraphrase swap + option shuffle). Loads corpus once.</summary>
        private JObject HandleDialogue(JObject req)
        {
            if (req["corpus_path"] != null && !DialogueInterceptor.Corpus.Loaded)
            {
                string path = req["corpus_path"].Value<string>();
                bool ok = DialogueInterceptor.Corpus.Load(path);
                Logger.LogInfo(string.Format("[dialogue] corpus load {0}: {1} options, version '{2}'",
                    ok ? "ok" : "FAILED", DialogueInterceptor.Corpus.Count, DialogueInterceptor.Corpus.Version));
            }
            if (req["seed"] != null) DialogueInterceptor.Seed = req["seed"].Value<ulong>();
            if (req["active"] != null) DialogueInterceptor.Active = req["active"].Value<bool>();
            return new JObject
            {
                ["active"] = DialogueInterceptor.Active,
                ["corpus_loaded"] = DialogueInterceptor.Corpus.Loaded,
                ["corpus_count"] = DialogueInterceptor.Corpus.Count
            };
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

        /// <summary>start_conv: {file} — start a conversation with the player as owner (debug/test).</summary>
        private JObject HandleStartConv(JObject req)
        {
            string file = req["file"].Value<string>();
            var cm = ConversationManager.Instance;
            if (cm == null) return new JObject { ["ok"] = false, ["error"] = "no ConversationManager" };
            GameObject owner = null;
            if (SDK.GameState.s_playerCharacter != null)
                owner = SDK.GameState.s_playerCharacter.gameObject;
            FlowChartPlayer p = cm.StartConversation(file, owner, FlowChartPlayer.DisplayMode.Standard, false);
            return new JObject { ["started"] = p != null };
        }

        private JObject HandleDiagDialogue(JObject req)
        {
            return new JObject
            {
                ["active"] = DialogueInterceptor.Active,
                ["corpus_loaded"] = DialogueInterceptor.Corpus.Loaded,
                ["corpus_count"] = DialogueInterceptor.Corpus.Count,
                ["get_node_text_calls"] = DialogueInterceptor.GetNodeTextCalls,
                ["swap_count"] = DialogueInterceptor.SwapCount,
                ["last_conv"] = DialogueInterceptor.LastConv,
                ["last_node"] = DialogueInterceptor.LastNode,
                ["last_for_player_input"] = DialogueInterceptor.LastForPlayerInput,
                ["last_had_variant"] = DialogueInterceptor.LastHadVariant
            };
        }

        /// <summary>diag_rng: cross-language RNG check. Returns the first 3 outputs
        /// of SplitMix64(seed) and hash64(text) so Python can assert parity.</summary>
        private JObject HandleDiagRng(JObject req)
        {
            ulong seed = req["seed"] != null ? req["seed"].Value<ulong>() : 0UL;
            string text = req["text"] != null ? req["text"].Value<string>() : "";
            var rng = new SplitMix64(seed);
            return new JObject
            {
                ["seq"] = new JArray(rng.NextU64().ToString(), rng.NextU64().ToString(), rng.NextU64().ToString()),
                ["hash"] = SplitMix64.Hash64(text).ToString()
            };
        }

        /// <summary>diag_asm: enumerate loaded assemblies (duplicate-copy detection).</summary>
        private JObject HandleDiagAsm(JObject req)
        {
            var arr = new JArray();
            foreach (System.Reflection.Assembly asm in AppDomain.CurrentDomain.GetAssemblies())
            {
                string name = asm.GetName().Name;
                if (name.IndexOf("Assembly-CSharp", StringComparison.OrdinalIgnoreCase) < 0 &&
                    name.IndexOf("Polenter", StringComparison.OrdinalIgnoreCase) < 0 &&
                    name.IndexOf("OEIFormats", StringComparison.OrdinalIgnoreCase) < 0)
                    continue;
                string loc;
                try { loc = asm.Location; } catch { loc = "<dynamic>"; }
                arr.Add(new JObject { ["name"] = name, ["location"] = loc, ["hash"] = asm.GetHashCode() });
            }
            // Where does the serializer's property type live, seen from our context?
            Type complexProp = AccessTools.TypeByName("Polenter.Serialization.Core.ComplexProperty");
            return new JObject
            {
                ["assemblies"] = arr,
                ["complex_property_asm"] = complexProp != null ? complexProp.Assembly.GetName().Name + " #" + complexProp.Assembly.GetHashCode() : "<not found>",
                ["game_utils_valid"] = SDK.GameUtilities.InstanceIsValid,
                ["game_cursor"] = SDK.GameCursor.Instance != null,
                ["scene"] = SDK.GameState.LoadedLevelName ?? ""
            };
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
                ["world_pick"] = new JArray(GameInput.WorldMousePosition.x, GameInput.WorldMousePosition.y, GameInput.WorldMousePosition.z),
                ["world_pick_on_nav"] = GameInput.WorldMousePositionOnNav,
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
