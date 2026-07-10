using System;
using System.Collections.Generic;
using System.IO;
using System.Reflection;
using HarmonyLib;

namespace CRPGBridge
{
    /// <summary>
    /// Per-episode dialogue randomizer (build brief §9). Postfixes:
    ///  - Conversation.GetNodeText(...) : replaces a player option's text with a
    ///    deterministically-chosen paraphrase from the corpus.
    ///  - Conversation.GetResponseNodes(player) : shuffles option order.
    /// Both derive from the episode seed keyed on (conv, node), so display and
    /// selection see the same order (the engine re-reads the shuffled list for
    /// both), and the agent can never rely on wording or position — only meaning.
    /// Applied only when Active and a corpus is loaded.
    /// </summary>
    public static class DialogueInterceptor
    {
        public static bool Active;
        public static ulong Seed;
        public static readonly Corpus Corpus = new Corpus();
        public static Action<string> Log = delegate { };

        // Diagnostics (surfaced via diag op).
        public static int GetNodeTextCalls;
        public static int SwapCount;
        public static string LastConv = "";
        public static int LastNode = -1;
        public static bool LastForPlayerInput;
        public static bool LastHadVariant;

        private const ulong ShuffleSalt = 0xA5A5A5A5A5A5A5A5UL;

        private static PropertyInfo _filenameProp; // FlowChart.Filename

        public static void Apply(Harmony harmony)
        {
            Type conversation = AccessTools.TypeByName("Conversation");
            if (conversation == null) { Log("Conversation type not found"); return; }

            // GetNodeText(FlowChartPlayer, FlowChartNode, bool, Conversation.NodeTextRequestType)
            MethodInfo getNodeText = null;
            foreach (MethodInfo m in conversation.GetMethods(BindingFlags.Public | BindingFlags.Instance))
            {
                if (m.Name == "GetNodeText") { getNodeText = m; break; }
            }
            if (getNodeText != null)
                harmony.Patch(getNodeText, postfix: new HarmonyMethod(
                    typeof(DialogueInterceptor).GetMethod(nameof(PostGetNodeText), BindingFlags.NonPublic | BindingFlags.Static)));
            else Log("GetNodeText not found");

            MethodInfo getResponses = AccessTools.Method(conversation, "GetResponseNodes", new[] { AccessTools.TypeByName("FlowChartPlayer") });
            if (getResponses != null)
                harmony.Patch(getResponses, postfix: new HarmonyMethod(
                    typeof(DialogueInterceptor).GetMethod(nameof(PostGetResponseNodes), BindingFlags.NonPublic | BindingFlags.Static)));
            else Log("GetResponseNodes(player) not found");

            _filenameProp = AccessTools.Property(AccessTools.TypeByName("FlowChart"), "Filename");
        }

        private static string ConvName(object conversation)
        {
            try
            {
                string full = _filenameProp != null ? _filenameProp.GetValue(conversation, null) as string : null;
                if (string.IsNullOrEmpty(full)) return "";
                return Path.GetFileNameWithoutExtension(full).ToLowerInvariant();
            }
            catch { return ""; }
        }

        private static int NodeId(object node)
        {
            if (node == null) return -1;
            FieldInfo f = AccessTools.Field(node.GetType(), "NodeID");
            if (f == null) return -1;
            try { return (int)f.GetValue(node); }
            catch { return -1; }
        }

        // Use untyped __args to avoid coupling to OEIFormats types.
        // GetNodeText(player, node, forPlayerInput, requestType): args[1]=node, args[2]=forPlayerInput.
        private static void PostGetNodeText(object __instance, object[] __args, ref string __result)
        {
            GetNodeTextCalls++;
            if (!Active || !Corpus.Loaded) return;
            if (__args == null || __args.Length < 3) return;
            bool forPlayerInput = __args[2] is bool && (bool)__args[2];
            LastForPlayerInput = forPlayerInput;
            if (!forPlayerInput) return;
            int nodeId = NodeId(__args[1]);
            string conv = ConvName(__instance);
            LastConv = conv; LastNode = nodeId;
            if (nodeId < 0 || conv.Length == 0) return;
            string variant = Corpus.PickVariant(conv, nodeId, Seed);
            LastHadVariant = variant != null;
            if (variant != null) { __result = variant; SwapCount++; }
        }

        // __result is List<PlayerResponseNode>, which implements IList — mutate in place.
        private static void PostGetResponseNodes(object __instance, System.Collections.IList __result)
        {
            if (!Active || __result == null || __result.Count < 2) return;
            int questionNode = CurrentQuestionNode();
            string conv = ConvName(__instance);
            ulong stream = Seed ^ SplitMix64.Hash64(conv) ^ (ulong)(uint)questionNode ^ ShuffleSalt;
            var rng = new SplitMix64(stream);
            for (int i = __result.Count - 1; i > 0; i--)
            {
                int j = (int)(rng.NextU64() % (ulong)(i + 1));
                object tmp = __result[i];
                __result[i] = __result[j];
                __result[j] = tmp;
            }
        }

        private static int CurrentQuestionNode()
        {
            try
            {
                var cm = ConversationManager.Instance;
                if (cm == null) return -1;
                FlowChartPlayer p = cm.GetActiveConversationForHUD();
                return p != null ? p.CurrentNodeID : -1;
            }
            catch { return -1; }
        }
    }
}
