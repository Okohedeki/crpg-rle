using System;
using BepInEx;
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

        private void Awake()
        {
            int instanceId = ParseIntEnv("CRPG_INSTANCE_ID", 0);
            int port = ParseIntEnv("CRPG_BRIDGE_PORT", 5555 + instanceId);

            _ipc = new IpcServer(port);
            _ipc.Register("handshake", HandleHandshake);
            _ipc.Register("ping", req => new JObject());
            _ipc.Register("shutdown", HandleShutdown);
            _ipc.Start();

            Logger.LogInfo(string.Format(
                "{0} v{1} loaded. Unity {2}, instance {3}, IPC listening on 127.0.0.1:{4}",
                PluginName, PluginVersion, Application.unityVersion, instanceId, port));
        }

        private void Update()
        {
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

        private void OnDestroy()
        {
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
