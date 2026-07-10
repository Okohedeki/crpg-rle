using BepInEx;
using UnityEngine;

namespace CRPGBridge
{
    [BepInPlugin(PluginGuid, PluginName, PluginVersion)]
    public class Plugin : BaseUnityPlugin
    {
        public const string PluginGuid = "com.crpgrle.bridge";
        public const string PluginName = "CRPG Bridge";
        public const string PluginVersion = "0.1.0";

        private void Awake()
        {
            Logger.LogInfo(string.Format(
                "{0} v{1} loaded. Unity {2}, instance id '{3}', product '{4}'",
                PluginName, PluginVersion,
                Application.unityVersion,
                System.Environment.GetEnvironmentVariable("CRPG_INSTANCE_ID") ?? "0",
                Application.productName));
        }
    }
}
