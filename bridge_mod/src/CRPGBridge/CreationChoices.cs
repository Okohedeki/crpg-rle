using System.Collections.Generic;
using Newtonsoft.Json.Linq;
using UnityEngine;

namespace CRPGBridge
{
    /// <summary>
    /// Structured character-creation choices. Each selectable option on the
    /// current creation stage is a UICharacterCreationEnumSetter whose Set()
    /// is exactly what the UI click path calls (OnButtonClicked -> Set). We
    /// enumerate them in deterministic screen order so the agent can choose
    /// "option i" with a number key — no cursor geometry involved — and the
    /// game applies the choice through its own validated code path.
    /// </summary>
    public static class CreationChoices
    {
        private static List<UICharacterCreationEnumSetter> Enumerate()
        {
            var setters = new List<UICharacterCreationEnumSetter>();
            foreach (var s in Object.FindObjectsOfType<UICharacterCreationEnumSetter>())
            {
                if (s != null && s.gameObject.activeInHierarchy) setters.Add(s);
            }
            // Deterministic screen order: top-to-bottom, then left-to-right.
            setters.Sort((a, b) =>
            {
                Vector3 pa = a.transform.position, pb = b.transform.position;
                int byY = pb.y.CompareTo(pa.y);
                return byY != 0 ? byY : pa.x.CompareTo(pb.x);
            });
            return setters;
        }

        private static string LabelFor(UICharacterCreationEnumSetter s)
        {
            var label = s.GetComponentInChildren<UILabel>();
            if (label != null && !string.IsNullOrEmpty(label.text)) return label.text;
            return s.gameObject.name;
        }

        public static JObject ListOptions()
        {
            var result = new JObject { ["in_creation"] = UICharacterCreationManager.Instance != null };
            var arr = new JArray();
            if (UICharacterCreationManager.Instance != null)
            {
                var setters = Enumerate();
                for (int i = 0; i < setters.Count; i++)
                {
                    arr.Add(new JObject
                    {
                        ["i"] = i,
                        ["type"] = setters[i].SetType.ToString(),
                        ["label"] = LabelFor(setters[i])
                    });
                }
                result["stage"] = UICharacterCreationManager.Instance.CurrentStage;
            }
            result["options"] = arr;
            return result;
        }

        public static JObject Choose(int index)
        {
            var setters = Enumerate();
            if (index < 0 || index >= setters.Count)
                return new JObject { ["ok"] = false, ["error"] = "option index out of range (" + setters.Count + " options)" };
            setters[index].Set(); // the same call the UI click makes
            return new JObject { ["chosen"] = index, ["type"] = setters[index].SetType.ToString() };
        }
    }
}
