using System;
using System.Collections.Generic;
using System.IO;
using System.Net;
using System.Net.Sockets;
using System.Text;
using System.Threading;
using Newtonsoft.Json.Linq;

namespace CRPGBridge
{
    /// <summary>
    /// TCP request/response server. A socket thread accepts one client and reads
    /// framed JSON requests; each request is handed to the Unity main thread
    /// (via Pump(), called from Plugin.Update) and the response is sent back
    /// before the next request is read. Framing: 4-byte little-endian length +
    /// UTF-8 JSON. One in-flight request at a time by design.
    /// </summary>
    public class IpcServer : IDisposable
    {
        public delegate JObject Handler(JObject request);

        private readonly int _port;
        private readonly Dictionary<string, Handler> _handlers = new Dictionary<string, Handler>();
        private readonly object _gate = new object();

        private TcpListener _listener;
        private Thread _thread;
        private volatile bool _running;

        /// <summary>Diagnostic sink; wired to the BepInEx logger by the plugin.</summary>
        public Action<string> Log = delegate { };

        // Single-slot handoff between socket thread and main thread.
        private JObject _pendingRequest;
        private JObject _pendingResponse;
        private readonly ManualResetEvent _responseReady = new ManualResetEvent(false);

        public IpcServer(int port)
        {
            _port = port;
        }

        public void Register(string op, Handler handler)
        {
            lock (_gate) _handlers[op] = handler;
        }

        public void Start()
        {
            _running = true;
            _listener = new TcpListener(IPAddress.Loopback, _port);
            _listener.Start();
            Log("listener started on " + _listener.LocalEndpoint);
            _thread = new Thread(SocketLoop) { IsBackground = true, Name = "CRPGBridge.Ipc" };
            _thread.Start();
            Log("socket thread started, alive=" + _thread.IsAlive);
        }

        /// <summary>Call from Unity main thread every frame; executes at most one pending request.</summary>
        public void Pump()
        {
            JObject request;
            lock (_gate)
            {
                if (_pendingRequest == null) return;
                request = _pendingRequest;
                _pendingRequest = null;
            }

            JObject response = Dispatch(request);
            lock (_gate) _pendingResponse = response;
            _responseReady.Set();
        }

        private JObject Dispatch(JObject request)
        {
            var response = new JObject();
            JToken idTok;
            if (request.TryGetValue("id", out idTok)) response["id"] = idTok;

            string op = null;
            JToken opTok;
            if (request.TryGetValue("op", out opTok)) op = opTok.Value<string>();

            Handler handler = null;
            if (op != null)
            {
                lock (_gate) _handlers.TryGetValue(op, out handler);
            }

            if (handler == null)
            {
                response["ok"] = false;
                response["error"] = "unknown op: " + (op ?? "<missing>");
                return response;
            }

            try
            {
                JObject result = handler(request) ?? new JObject();
                if (result["ok"] == null) result["ok"] = true;
                if (idTok != null) result["id"] = idTok;
                return result;
            }
            catch (Exception ex)
            {
                response["ok"] = false;
                response["error"] = ex.GetType().Name + ": " + ex.Message;
                return response;
            }
        }

        private void SocketLoop()
        {
            while (_running)
            {
                TcpClient client = null;
                try
                {
                    Log("accepting on port " + _port);
                    client = _listener.AcceptTcpClient();
                    client.NoDelay = true;
                    Log("client connected: " + client.Client.RemoteEndPoint);
                    ServeClient(client.GetStream());
                    Log("client disconnected");
                }
                catch (SocketException ex)
                {
                    // Listener stopped or accept failed; exit if shutting down.
                    if (!_running) return;
                    Log("SocketException in accept/serve: " + ex.Message);
                    Thread.Sleep(500); // avoid a tight failure loop
                }
                catch (IOException ex)
                {
                    // Client vanished mid-frame; go back to accepting.
                    Log("IOException (client vanished): " + ex.Message);
                }
                catch (Exception ex)
                {
                    Log("unexpected in socket loop: " + ex);
                    Thread.Sleep(500);
                }
                finally
                {
                    if (client != null) client.Close();
                    // Drop any half-processed exchange.
                    lock (_gate) { _pendingRequest = null; _pendingResponse = null; }
                }
            }
        }

        private void ServeClient(NetworkStream stream)
        {
            while (_running)
            {
                JObject request = ReadFrame(stream);
                if (request == null) return; // clean disconnect

                _responseReady.Reset();
                lock (_gate) _pendingRequest = request;

                // Wait for the main thread to pump a response.
                _responseReady.WaitOne();

                JObject response;
                lock (_gate) { response = _pendingResponse; _pendingResponse = null; }
                if (response == null) continue;
                WriteFrame(stream, response);
            }
        }

        private static JObject ReadFrame(NetworkStream stream)
        {
            byte[] header = ReadExact(stream, 4);
            if (header == null) return null;
            int length = header[0] | (header[1] << 8) | (header[2] << 16) | (header[3] << 24);
            if (length <= 0 || length > 64 * 1024 * 1024)
                throw new IOException("bad frame length " + length);
            byte[] payload = ReadExact(stream, length);
            if (payload == null) return null;
            return JObject.Parse(Encoding.UTF8.GetString(payload));
        }

        private static void WriteFrame(NetworkStream stream, JObject obj)
        {
            byte[] payload = Encoding.UTF8.GetBytes(obj.ToString(Newtonsoft.Json.Formatting.None));
            byte[] header = new byte[4]
            {
                (byte)(payload.Length & 0xFF),
                (byte)((payload.Length >> 8) & 0xFF),
                (byte)((payload.Length >> 16) & 0xFF),
                (byte)((payload.Length >> 24) & 0xFF)
            };
            stream.Write(header, 0, 4);
            stream.Write(payload, 0, payload.Length);
            stream.Flush();
        }

        private static byte[] ReadExact(NetworkStream stream, int count)
        {
            byte[] buf = new byte[count];
            int offset = 0;
            while (offset < count)
            {
                int read = stream.Read(buf, offset, count - offset);
                if (read <= 0) return null;
                offset += read;
            }
            return buf;
        }

        public void Dispose()
        {
            _running = false;
            _responseReady.Set();
            if (_listener != null) _listener.Stop();
            if (_thread != null) _thread.Join(1000);
        }
    }
}
