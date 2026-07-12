using System;
using System.Reflection;
using HarmonyLib;
using Newtonsoft.Json.Linq;

namespace CRPGBridge.Hooks
{
    /// <summary>
    /// Installs the engine-event taps that feed EventLog:
    ///  - reputation mutations (postfix on ReputationManager.Add/RemoveReputation)
    ///  - quest end-states (postfix on QuestManager.TriggerQuestEndState)
    ///  - global-variable writes (postfix on QuestManager.TriggerGlobalVariableEvent)
    ///  - area load/unload + combat start/end (static GameState events)
    ///  - conversation start/end + player dialogue choice
    /// Instance-delegate subscriptions (quests, conversations) are re-attempted
    /// from Tick() because the managers don't exist until a game is loaded.
    /// </summary>
    public static class EventHooks
    {
        public static Action<string> Log = delegate { };
        private static bool _questDelegatesHooked;
        private static bool _convDelegatesHooked;

        public static void Install(Harmony harmony)
        {
            // --- static events: available immediately -----------------------
            SDK.GameState.CombatStart += (s, e) => EventLog.Add("combat", new JObject { ["active"] = true });
            SDK.GameState.CombatEnd += (s, e) => EventLog.Add("combat", new JObject { ["active"] = false });
            SDK.GameState.LevelLoaded += (s, e) => EventLog.Add("area", new JObject
            {
                ["event"] = "loaded",
                ["area"] = SDK.GameState.LoadedLevelName ?? ""
            });
            SDK.GameState.LevelUnload += (s, e) => EventLog.Add("area", new JObject
            {
                ["event"] = "unload",
                ["area"] = SDK.GameState.LoadedLevelName ?? ""
            });

            // --- reputation mutators ----------------------------------------
            TryPatch(harmony, typeof(Game.ReputationManager), "AddReputation",
                new[] { typeof(SDK.Reputation), typeof(SDK.Reputation.Axis), typeof(SDK.Reputation.ChangeStrength), typeof(int), typeof(bool) },
                nameof(PostAddReputation));
            TryPatch(harmony, typeof(Game.ReputationManager), "RemoveReputation",
                new[] { typeof(SDK.Reputation), typeof(SDK.Reputation.Axis), typeof(SDK.Reputation.ChangeStrength), typeof(int), typeof(bool) },
                nameof(PostRemoveReputation));

            // --- quest end states + global vars ------------------------------
            TryPatch(harmony, typeof(SDK.QuestManager), "TriggerQuestEndState",
                new[] { typeof(string), typeof(int), typeof(bool) }, nameof(PostQuestEndStateByName));
            TryPatch(harmony, typeof(SDK.QuestManager), "TriggerGlobalVariableEvent",
                new[] { typeof(string), typeof(int) }, nameof(PostGlobalVariable));

            // --- player dialogue choice --------------------------------------
            TryPatch(harmony, typeof(UIConversationManager), "PlayerInput",
                new[] { typeof(int) }, nameof(PostPlayerInput));
        }

        /// <summary>Call every frame; attaches instance delegates once managers exist.</summary>
        public static void Tick()
        {
            if (!_questDelegatesHooked && SDK.QuestManager.Instance != null)
            {
                var qm = SDK.QuestManager.Instance;
                qm.OnQuestStarted = (SDK.QuestManager.QuestDelegate)Delegate.Combine(
                    qm.OnQuestStarted, new SDK.QuestManager.QuestDelegate(q => QuestEvent("started", q)));
                qm.OnQuestAdvanced = (SDK.QuestManager.QuestDelegate)Delegate.Combine(
                    qm.OnQuestAdvanced, new SDK.QuestManager.QuestDelegate(q => QuestEvent("advanced", q)));
                qm.OnQuestCompleted = (SDK.QuestManager.QuestDelegate)Delegate.Combine(
                    qm.OnQuestCompleted, new SDK.QuestManager.QuestDelegate(q => QuestEvent("completed", q)));
                qm.OnQuestFailed = (SDK.QuestManager.QuestDelegate)Delegate.Combine(
                    qm.OnQuestFailed, new SDK.QuestManager.QuestDelegate(q => QuestEvent("failed", q)));
                _questDelegatesHooked = true;
                Log("quest delegates hooked");
            }

            if (!_convDelegatesHooked && ConversationManager.Instance != null)
            {
                var cm = ConversationManager.Instance;
                cm.FlowChartPlayerAdded = (ConversationManager.FlowChartPlayerDelegate)Delegate.Combine(
                    cm.FlowChartPlayerAdded, new ConversationManager.FlowChartPlayerDelegate(p => ConvEvent("start", p)));
                cm.FlowChartPlayerRemoved = (ConversationManager.FlowChartPlayerDelegate)Delegate.Combine(
                    cm.FlowChartPlayerRemoved, new ConversationManager.FlowChartPlayerDelegate(p => ConvEvent("end", p)));
                _convDelegatesHooked = true;
                Log("conversation delegates hooked");
            }
        }

        private static void QuestEvent(string what, object quest)
        {
            string name = "";
            try
            {
                if (quest != null)
                {
                    PropertyInfo fn = quest.GetType().GetProperty("Filename");
                    if (fn != null) name = (fn.GetValue(quest, null) as string) ?? "";
                }
            }
            catch { }
            EventLog.Add("quest", new JObject { ["event"] = what, ["quest"] = name });
        }

        private static void ConvEvent(string what, FlowChartPlayer player)
        {
            string file = "";
            try
            {
                if (player != null && player.CurrentFlowChart != null)
                    file = player.CurrentFlowChart.Filename ?? "";
            }
            catch { }
            EventLog.Add("conversation", new JObject { ["event"] = what, ["file"] = file });
        }

        private static void TryPatch(Harmony harmony, Type target, string method, Type[] sig, string postfixName)
        {
            try
            {
                MethodInfo m = AccessTools.Method(target, method, sig);
                if (m == null) throw new MissingMethodException(target.Name + "." + method);
                harmony.Patch(m, postfix: new HarmonyMethod(
                    typeof(EventHooks).GetMethod(postfixName, BindingFlags.NonPublic | BindingFlags.Static)));
            }
            catch (Exception ex)
            {
                Log("event patch FAILED " + target.Name + "." + method + ": " + ex.Message);
            }
        }

        private static void PostAddReputation(SDK.Reputation rep, SDK.Reputation.Axis axis,
            SDK.Reputation.ChangeStrength strength, int reasonIndex, bool __result)
        {
            ReputationEvent("add", rep, axis, strength, __result);
        }

        private static void PostRemoveReputation(SDK.Reputation rep, SDK.Reputation.Axis axis,
            SDK.Reputation.ChangeStrength strength, int reasonIndex, bool __result)
        {
            ReputationEvent("remove", rep, axis, strength, __result);
        }

        private static void ReputationEvent(string what, SDK.Reputation rep,
            SDK.Reputation.Axis axis, SDK.Reputation.ChangeStrength strength, bool applied)
        {
            string faction = "";
            var gameRep = rep as Game.Reputation;
            if (gameRep != null) faction = gameRep.FactionID.ToString();
            EventLog.Add("reputation", new JObject
            {
                ["event"] = what,
                ["faction"] = faction,
                ["axis"] = axis.ToString().ToLowerInvariant(),   // positive = Favor, negative = Wrath
                ["strength"] = (int)strength,
                ["applied"] = applied
            });
        }

        private static void PostQuestEndStateByName(string questName, int endStateID, bool failed)
        {
            EventLog.Add("quest_end_state", new JObject
            {
                ["quest"] = questName ?? "",
                ["end_state"] = endStateID,
                ["failed"] = failed
            });
        }

        private static void PostGlobalVariable(string globalVariableName, int variableValue)
        {
            EventLog.Add("global_var", new JObject
            {
                ["name"] = globalVariableName ?? "",
                ["value"] = variableValue
            });
        }

        private static void PostPlayerInput(int number)
        {
            EventLog.Add("dialogue_choice", new JObject { ["index"] = number });
        }
    }
}
