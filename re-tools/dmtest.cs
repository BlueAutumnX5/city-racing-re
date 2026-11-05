// dmtest.cs - replays City Racing's engine-sound calls against the real (32-bit) DirectMusic,
// and records the actual audio output with WASAPI loopback, to measure loop gaps.
// Mirrors game.exe: CAudioManager init 0x46dac0, CGameSound setup 0x46ba50 / ctor 0x46bda0,
// Play(loop) 0x46b410, IsPlaying 0x46b690, engine update 0x46cd60.
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading;

public static class DmTest
{
    [UnmanagedFunctionPointer(CallingConvention.StdCall)] delegate int F0(IntPtr t);
    [UnmanagedFunctionPointer(CallingConvention.StdCall)] delegate int F1i(IntPtr t, int a);
    [UnmanagedFunctionPointer(CallingConvention.StdCall)] delegate int F2i(IntPtr t, int a, int b);
    [UnmanagedFunctionPointer(CallingConvention.StdCall)] delegate int F1p(IntPtr t, IntPtr a);
    [UnmanagedFunctionPointer(CallingConvention.StdCall)] delegate int FoutI(IntPtr t, out int a);
    [UnmanagedFunctionPointer(CallingConvention.StdCall)] delegate int FGetObj(IntPtr t, IntPtr desc, ref Guid iid, out IntPtr ppv);
    [UnmanagedFunctionPointer(CallingConvention.StdCall)] delegate int FEnableCache(IntPtr t, ref Guid g, int f);
    [UnmanagedFunctionPointer(CallingConvention.StdCall)] delegate int FInitAudio(IntPtr t, IntPtr ppDM, IntPtr ppDS, IntPtr hwnd, int type, int pch, int flags, IntPtr parms);
    [UnmanagedFunctionPointer(CallingConvention.StdCall)] delegate int FCreatePath(IntPtr t, int type, int pch, int act, out IntPtr path);
    [UnmanagedFunctionPointer(CallingConvention.StdCall)] delegate int FGetObjInPath(IntPtr t, int pch, int stage, int buf, ref Guid obj, int idx, ref Guid iid, out IntPtr ppv);
    [UnmanagedFunctionPointer(CallingConvention.StdCall)] delegate int FSetTrackConfig(IntPtr t, ref Guid cls, int grp, int idx, int on, int off);
    [UnmanagedFunctionPointer(CallingConvention.StdCall)] delegate int FPlaySeg(IntPtr t, IntPtr seg, IntPtr name, IntPtr trans, int flags, long start, out IntPtr ss, IntPtr from, IntPtr path);
    [UnmanagedFunctionPointer(CallingConvention.StdCall)] delegate int FStopEx(IntPtr t, IntPtr obj, long time, int flags);
    [UnmanagedFunctionPointer(CallingConvention.StdCall)] delegate int FQI(IntPtr t, ref Guid iid, out IntPtr ppv);
    [UnmanagedFunctionPointer(CallingConvention.StdCall)] delegate int FSet3(IntPtr t, float x, float y, float z, int apply);
    [UnmanagedFunctionPointer(CallingConvention.StdCall)] delegate int FSetF(IntPtr t, float v, int apply);
    [UnmanagedFunctionPointer(CallingConvention.StdCall)] delegate int FGetTime(IntPtr t, out long rt, out int mt);
    [UnmanagedFunctionPointer(CallingConvention.StdCall)] delegate int FM2R(IntPtr t, int mt, out long rt);
    [UnmanagedFunctionPointer(CallingConvention.StdCall)] delegate int FGetDefEp(IntPtr t, int flow, int role, out IntPtr dev);
    [UnmanagedFunctionPointer(CallingConvention.StdCall)] delegate int FActivate(IntPtr t, ref Guid iid, int ctx, IntPtr p, out IntPtr ppv);
    [UnmanagedFunctionPointer(CallingConvention.StdCall)] delegate int FInit(IntPtr t, int share, int flags, long dur, long per, IntPtr fmt, IntPtr sess);
    [UnmanagedFunctionPointer(CallingConvention.StdCall)] delegate int FGetService(IntPtr t, ref Guid iid, out IntPtr ppv);
    [UnmanagedFunctionPointer(CallingConvention.StdCall)] delegate int FGetMix(IntPtr t, out IntPtr fmt);
    [UnmanagedFunctionPointer(CallingConvention.StdCall)] delegate int FGetBuffer(IntPtr t, out IntPtr data, out int frames, out int flags, out long devpos, out long qpc);

    [DllImport("ole32.dll")] static extern int CoInitialize(IntPtr p);
    [DllImport("ole32.dll")] static extern int CoCreateInstance(ref Guid clsid, IntPtr outer, int ctx, ref Guid iid, out IntPtr ppv);
    [DllImport("dsound.dll")] static extern int DirectSoundCreate8(IntPtr guid, out IntPtr ds, IntPtr outer);
    [DllImport("user32.dll")] static extern IntPtr GetDesktopWindow();

    static T D<T>(IntPtr obj, int slot) where T : class
    {
        IntPtr vt = Marshal.ReadIntPtr(obj);
        return Marshal.GetDelegateForFunctionPointer(Marshal.ReadIntPtr(vt, slot * 4), typeof(T)) as T;
    }
    static void Ck(int hr, string what)
    {
        if (hr < 0) throw new Exception(what + " failed hr=0x" + hr.ToString("x8"));
    }

    static Guid CLSID_Perf = new Guid("d2ac2881-b39b-11d1-8704-00600893b1bd");
    static Guid IID_Perf8 = new Guid("679c4137-c62e-4147-b2b4-9d569acb254c");
    static Guid CLSID_Loader = new Guid("d2ac2892-b39b-11d1-8704-00600893b1bd");
    static Guid IID_Loader8 = new Guid("19e7c08c-0a44-4e6a-a116-595a7cd5de8c");
    static Guid GUID_AllTypes = new Guid("d2ac2893-b39b-11d1-8704-00600893b1bd");
    static Guid CLSID_Segment = new Guid("d2ac2882-b39b-11d1-8704-00600893b1bd");
    static Guid IID_Segment8 = new Guid("c6784488-41a3-418f-aa15-b35093ba42d4");
    static Guid IID_SegState8 = new Guid("a50e4730-0ae4-48a7-9839-bc04bfe07772");
    static Guid CLSID_WaveTrack = new Guid("eed36461-9ea5-11d3-9bd1-0080c7150a74");
    static Guid IID_DSB8 = new Guid("6825a449-7524-4d82-920f-50e36ab3ab1e");
    static Guid IID_DS3DB = new Guid("279afa86-4981-11ce-a521-0020af0be560");
    static Guid GUID_Null = Guid.Empty;
    static Guid CLSID_MMDevEnum = new Guid("BCDE0395-E52F-467C-8E3D-C4579291692E");
    static Guid IID_MMDevEnum = new Guid("A95664D2-9614-4F35-A746-DE8DB63617E6");
    static Guid IID_AudioClient = new Guid("1CB9AD4C-DBFA-4c32-B178-C2F568A703B2");
    static Guid IID_CaptureClient = new Guid("C8ADBD64-E71E-48a0-A4DE-185C395CD317");

    static IntPtr perf, loader, ds;
    static StringBuilder log = new StringBuilder();
    static void L(string s) { log.AppendLine(s); Console.WriteLine(s); }

    // ---------------- WASAPI loopback ----------------
    static IntPtr capClient, capture;
    static int capChannels, capRate;
    static bool capFloat;
    public class Bin { public double t; public double rms; }
    static List<Bin> bins = new List<Bin>();

    static void StartCapture()
    {
        IntPtr en, dev, ac;
        Ck(CoCreateInstance(ref CLSID_MMDevEnum, IntPtr.Zero, 0x17, ref IID_MMDevEnum, out en), "MMDeviceEnumerator");
        Ck(D<FGetDefEp>(en, 4)(en, 0, 0, out dev), "GetDefaultAudioEndpoint");
        Ck(D<FActivate>(dev, 3)(dev, ref IID_AudioClient, 0x17, IntPtr.Zero, out ac), "Activate");
        IntPtr fmt;
        Ck(D<FGetMix>(ac, 8)(ac, out fmt), "GetMixFormat");
        int tag = Marshal.ReadInt16(fmt, 0);
        capChannels = Marshal.ReadInt16(fmt, 2);
        capRate = Marshal.ReadInt32(fmt, 4);
        int bits = Marshal.ReadInt16(fmt, 14);
        capFloat = (tag == 3) || (tag == unchecked((short)0xFFFE) && bits == 32);
        L("loopback mix format: tag " + tag + " ch " + capChannels + " rate " + capRate + " bits " + bits + " float " + capFloat);
        Ck(D<FInit>(ac, 3)(ac, 0, 0x20000, 10000000L, 0L, fmt, IntPtr.Zero), "IAudioClient.Initialize(loopback)");
        Ck(D<FGetService>(ac, 14)(ac, ref IID_CaptureClient, out capture), "GetService(capture)");
        Ck(D<F0>(ac, 10)(ac), "Start");
        capClient = ac;
    }

    static double QpcToSec(long qpc100ns) { return qpc100ns / 1e7; }
    static double NowSec() { return Stopwatch.GetTimestamp() / (double)Stopwatch.Frequency; }

    static void PumpCapture()
    {
        while (true)
        {
            int n;
            if (D<FoutI>(capture, 5)(capture, out n) < 0 || n == 0) return;
            IntPtr p; int frames, flags; long devpos, qpc;
            if (D<FGetBuffer>(capture, 3)(capture, out p, out frames, out flags, out devpos, out qpc) < 0) return;
            double t0 = QpcToSec(qpc);
            // 5 ms bins inside the packet
            int per = Math.Max(1, capRate / 200);
            for (int f = 0; f < frames; f += per)
            {
                int cnt = Math.Min(per, frames - f);
                double acc = 0;
                if ((flags & 2) == 0 && capFloat)
                {
                    float[] buf = new float[cnt * capChannels];
                    Marshal.Copy(new IntPtr(p.ToInt64() + (long)f * capChannels * 4), buf, 0, buf.Length);
                    for (int i = 0; i < buf.Length; i++) acc += buf[i] * (double)buf[i];
                    acc /= buf.Length;
                }
                Bin b = new Bin(); b.t = t0 + (double)f / capRate; b.rms = Math.Sqrt(acc);
                bins.Add(b);
            }
            D<F1i>(capture, 4)(capture, frames);
        }
    }

    // ---------------- DirectMusic, as the game does it ----------------
    public class Voice
    {
        public IntPtr seg, path, buf, b3d, ss8;
        public int baseFreq, lenMt;
        public double startSec = -1;
        public List<double> triggers = new List<double>();
    }

    static void Init()
    {
        Ck(CoInitialize(IntPtr.Zero), "CoInitialize");
        Ck(DirectSoundCreate8(IntPtr.Zero, out ds, IntPtr.Zero), "DirectSoundCreate8");
        Ck(D<F2i>(ds, 6)(ds, GetDesktopWindow().ToInt32(), 2), "SetCooperativeLevel");
        Ck(CoCreateInstance(ref CLSID_Loader, IntPtr.Zero, 3, ref IID_Loader8, out loader), "loader");
        Ck(CoCreateInstance(ref CLSID_Perf, IntPtr.Zero, 3, ref IID_Perf8, out perf), "performance");
        IntPtr parms = Marshal.AllocHGlobal(0x28);
        for (int i = 0; i < 0x28; i += 4) Marshal.WriteInt32(parms, i, 0);
        Marshal.WriteInt32(parms, 0, 0x28); Marshal.WriteInt32(parms, 4, 1); Marshal.WriteInt32(parms, 8, 7);
        Marshal.WriteInt32(parms, 12, 0x31); Marshal.WriteInt32(parms, 16, 0x40); Marshal.WriteInt32(parms, 20, 0x5622);
        IntPtr ppds = Marshal.AllocHGlobal(4); Marshal.WriteIntPtr(ppds, ds);
        Ck(D<FInitAudio>(perf, 44)(perf, IntPtr.Zero, ppds, GetDesktopWindow(), 8, 0x40, 0, parms), "InitAudio");
        D<FEnableCache>(loader, 10)(loader, ref GUID_AllTypes, 0);
    }

    static Voice Load(byte[] wav, double[] out3d)
    {
        Voice v = new Voice();
        IntPtr mem = Marshal.AllocHGlobal(wav.Length); Marshal.Copy(wav, 0, mem, wav.Length);
        IntPtr desc = Marshal.AllocHGlobal(0x350);
        for (int i = 0; i < 0x350; i += 4) Marshal.WriteInt32(desc, i, 0);
        Marshal.WriteInt32(desc, 0, 0x350); Marshal.WriteInt32(desc, 4, 0x402);
        Marshal.Copy(CLSID_Segment.ToByteArray(), 0, new IntPtr(desc.ToInt64() + 0x18), 16);
        Marshal.WriteInt32(desc, 0x340, wav.Length); Marshal.WriteInt32(desc, 0x344, 0);
        Marshal.WriteIntPtr(desc, 0x348, mem);
        Ck(D<FGetObj>(loader, 3)(loader, desc, ref IID_Segment8, out v.seg), "GetObject(segment)");
        D<FoutI>(v.seg, 3)(v.seg, out v.lenMt);
        // CGameSound setup, type 2 (3D)
        Ck(D<FCreatePath>(perf, 49)(perf, 6, 0x40, 0, out v.path), "CreateStandardAudioPath");
        Ck(D<F1p>(v.seg, 29)(v.seg, v.path), "Download");
        Ck(D<FGetObjInPath>(v.path, 3)(v.path, unchecked((int)0xFFFFFFFB), 0x6000, 0, ref GUID_Null, 0, ref IID_DSB8, out v.buf), "GetObjectInPath(buffer)");
        D<FoutI>(v.buf, 8)(v.buf, out v.baseFreq);
        D<F1i>(v.buf, 15)(v.buf, -1000);                                   // SetVolume -10 dB (quiet test)
        Ck(D<FGetObjInPath>(v.path, 3)(v.path, 0, 0x6000, 0, ref GUID_Null, 0, ref IID_DS3DB, out v.b3d), "GetObjectInPath(3D)");
        D<FSet3>(v.b3d, 19)(v.b3d, 0f, 0f, 1f, 0);                          // SetPosition next to the listener
        D<FSetF>(v.b3d, 17)(v.b3d, 5f, 0); D<FSetF>(v.b3d, 16)(v.b3d, 50f, 0);
        D<FSetTrackConfig>(v.seg, 26)(v.seg, ref CLSID_WaveTrack, -1, unchecked((int)0x80000000), 0x40, 0);
        D<F1p>(v.seg, 30)(v.seg, v.path);                                  // Unload
        D<F1i>(v.seg, 4)(v.seg, 1);                                        // ctor: SetLength(1)
        D<F1i>(v.seg, 21)(v.seg, 0);                                       // SetStartPoint(0)
        D<F2i>(v.seg, 23)(v.seg, 0, 0);                                    // SetLoopPoints(0,0)
        return v;
    }

    public static int Mode = 0;   // 0 = stock game behaviour

    static void Play(Voice v, bool loop)
    {
        D<F1p>(v.seg, 29)(v.seg, v.path);                                  // Download
        D<F1i>(v.path, 4)(v.path, 1);                                      // Activate(TRUE)
        D<F1i>(v.seg, 6)(v.seg, loop ? -1 : 0);                            // SetRepeats
        D<F1i>(v.seg, 4)(v.seg, 1);                                        // SetLength(1)
        D<F1i>(v.seg, 21)(v.seg, 0);                                       // SetStartPoint(0)
        IntPtr ss;
        Ck(D<FPlaySeg>(perf, 45)(perf, v.seg, IntPtr.Zero, IntPtr.Zero, 0x4080, 0L, out ss, IntPtr.Zero, v.path), "PlaySegmentEx");
        D<FQI>(ss, 0)(ss, ref IID_SegState8, out v.ss8);
        D<F0>(ss, 2)(ss);
        v.startSec = NowSec();
        v.triggers.Add(v.startSec);
    }

    static bool GameIsPlaying(Voice v)
    {
        if (v.startSec >= 0 && NowSec() - v.startSec < 0.25) return true;
        if (v.ss8 == IntPtr.Zero) return false;
        return D<Fpp2>(perf, 14)(perf, IntPtr.Zero, v.ss8) == 0;
    }
    [UnmanagedFunctionPointer(CallingConvention.StdCall)] delegate int Fpp2(IntPtr t, IntPtr a, IntPtr b);

    [UnmanagedFunctionPointer(CallingConvention.StdCall)] delegate int FCreateBuf(IntPtr t, IntPtr desc, out IntPtr buf, IntPtr outer);
    [UnmanagedFunctionPointer(CallingConvention.StdCall)] delegate int FLock(IntPtr t, int off, int bytes, out IntPtr p1, out int n1, out IntPtr p2, out int n2, int flags);
    [UnmanagedFunctionPointer(CallingConvention.StdCall)] delegate int FUnlock(IntPtr t, IntPtr p1, int n1, IntPtr p2, int n2);
    [UnmanagedFunctionPointer(CallingConvention.StdCall)] delegate int FPlayDS(IntPtr t, int r, int prio, int flags);

    static int CapsFlags(IntPtr buf)
    {
        IntPtr caps = Marshal.AllocHGlobal(20);
        Marshal.WriteInt32(caps, 0, 20);
        D<F1p>(buf, 3)(buf, caps);
        return Marshal.ReadInt32(caps, 4);
    }

    public static int DsFlags = 0x380B0;   // CTRL3D|CTRLFREQUENCY|CTRLVOLUME|GLOBALFOCUS|GETCURRENTPOSITION2|MUTE3DATMAXDISTANCE (as DirectMusic's own 0x682b0)

    // The fix candidate: the engine wave in a plain DirectSound 3D buffer, looped by DirectSound itself.
    static Voice LoadDS(byte[] wav)
    {
        Voice v = new Voice();
        int dataLen = BitConverter.ToInt32(wav, 40);
        IntPtr fmt = Marshal.AllocHGlobal(18);
        Marshal.Copy(wav, 20, fmt, 16); Marshal.WriteInt16(fmt, 16, 0);
        IntPtr desc = Marshal.AllocHGlobal(36);
        for (int i = 0; i < 36; i += 4) Marshal.WriteInt32(desc, i, 0);
        Marshal.WriteInt32(desc, 0, 36); Marshal.WriteInt32(desc, 4, DsFlags); Marshal.WriteInt32(desc, 8, dataLen);
        Marshal.WriteIntPtr(desc, 16, fmt);
        IntPtr b;
        Ck(D<FCreateBuf>(ds, 3)(ds, desc, out b, IntPtr.Zero), "CreateSoundBuffer");
        IntPtr p1, p2; int n1, n2;
        Ck(D<FLock>(b, 11)(b, 0, dataLen, out p1, out n1, out p2, out n2, 0), "Lock");
        Marshal.Copy(wav, 44, p1, n1);
        if (p2 != IntPtr.Zero && n2 > 0) Marshal.Copy(wav, 44 + n1, p2, n2);
        D<FUnlock>(b, 19)(b, p1, n1, p2, n2);
        Ck(D<FQI>(b, 0)(b, ref IID_DSB8, out v.buf), "QI DSB8");
        Ck(D<FQI>(b, 0)(b, ref IID_DS3DB, out v.b3d), "QI 3D");
        D<F0>(b, 2)(b);
        D<FoutI>(v.buf, 8)(v.buf, out v.baseFreq);
        D<F1i>(v.buf, 15)(v.buf, -1000);
        D<FSet3>(v.b3d, 19)(v.b3d, 0f, 0f, 1f, 0);
        D<FSetF>(v.b3d, 17)(v.b3d, 5f, 0); D<FSetF>(v.b3d, 16)(v.b3d, 50f, 0);
        return v;
    }

    static bool DsIsPlaying(Voice v)
    {
        int st; D<FoutI>(v.buf, 9)(v.buf, out st);
        return (st & 1) != 0;
    }

    static void Stop(Voice v)
    {
        D<FStopEx>(perf, 46)(perf, v.seg, 0L, 0);
        if (v.ss8 != IntPtr.Zero) { D<F0>(v.ss8, 2)(v.ss8); v.ss8 = IntPtr.Zero; }
        D<F1i>(v.path, 4)(v.path, 0);
        D<F1p>(v.seg, 30)(v.seg, v.path);
    }

    // Runs the engine update loop (0x46cd60) for `secs` seconds at a fixed pitch ratio.
    static void RunCase(string name, byte[] wav, double ratio, double secs, int mode)
    {
        Voice v = mode == 0 ? Load(wav, null) : LoadDS(wav);
        int samples = BitConverter.ToInt32(wav, 40) / 2;
        double lenSec = samples / 22050.0;
        L("");
        L("=== " + (mode == 0 ? "STOCK DirectMusic " : "FIX DirectSound loop ") + name + "  pitch x" + ratio.ToString("0.00") + "  (wave " + lenSec.ToString("0.000") + " s, segment length " + v.lenMt + " ticks, buffer base " + v.baseFreq + " Hz)");
        PumpCapture();
        double c0 = NowSec();
        double next = c0;
        while (NowSec() - c0 < secs)
        {
            D<F1i>(v.buf, 17)(v.buf, (int)(v.baseFreq * ratio));          // SetFrequency every frame
            if (mode == 0) { if (!GameIsPlaying(v)) Play(v, true); }
            else if (!DsIsPlaying(v)) { D<FPlayDS>(v.buf, 12)(v.buf, 0, 0, 1); v.startSec = NowSec(); v.triggers.Add(v.startSec); }
            PumpCapture();
            next += 0.008;                                                   // ~125 FPS frame pacing
            while (NowSec() < next) Thread.Sleep(0);
        }
        if (mode == 0) { L("  DirectMusic audiopath buffer caps flags 0x" + CapsFlags(v.buf).ToString("x")); Stop(v); }
        else { L("  DirectSound buffer caps flags 0x" + CapsFlags(v.buf).ToString("x")); D<F0>(v.buf, 18)(v.buf); }
        double stopAt = NowSec();
        Thread.Sleep(300);
        PumpCapture();
        // analysis: triggers and silent stretches in the captured output
        StringBuilder tr = new StringBuilder();
        for (int i = 0; i < v.triggers.Count; i++) tr.Append((v.triggers[i] - c0).ToString("0.000") + "  ");
        L("  game (re)triggers at: " + tr);
        double thr = 0.003;   // ~ -50 dBFS
        double silStart = -1; double lastT = -1;
        List<string> gaps = new List<string>();
        double sound = 0, total = 0;
        foreach (Bin b in bins)
        {
            if (b.t < c0 - 0.05 || b.t > stopAt) continue;
            double rel = b.t - c0;
            total += 0.005;
            if (b.rms >= thr) sound += 0.005;
            if (b.rms < thr) { if (silStart < 0) silStart = rel; }
            else { if (silStart >= 0 && rel - silStart >= 0.03) gaps.Add(silStart.ToString("0.000") + "-" + rel.ToString("0.000") + " (" + ((rel - silStart) * 1000).ToString("0") + " ms)"); silStart = -1; }
            lastT = rel;
        }
        if (silStart >= 0) gaps.Add(silStart.ToString("0.000") + "-end");
        L("  silent stretches (>30 ms, <-50 dBFS): " + (gaps.Count == 0 ? "none" : string.Join(", ", gaps.ToArray())));
        double lv = 0; int ln = 0;
        foreach (Bin b in bins) { if (b.t > c0 + 0.3 && b.t < stopAt && b.rms >= thr) { lv += b.rms; ln++; } }
        L("  mean level while audible: " + (ln > 0 ? (20 * Math.Log10(lv / ln)).ToString("0.0") + " dBFS" : "n/a"));
        // ENVELOPE: 25 ms bins relative to the median level; report dips > 10 dB
        List<double> env = new List<double>(); List<double> et = new List<double>();
        double acc2 = 0; int k = 0; double tb = -1;
        foreach (Bin b in bins)
        {
            if (b.t < c0 + 0.15 || b.t > stopAt) continue;
            if (tb < 0) tb = b.t;
            acc2 += b.rms * b.rms; k++;
            if (k == 5) { env.Add(10 * Math.Log10(acc2 / 5 + 1e-12)); et.Add(tb - c0); acc2 = 0; k = 0; tb = -1; }
        }
        if (env.Count > 4)
        {
            List<double> sorted = new List<double>(env); sorted.Sort();
            double med = sorted[sorted.Count / 2];
            StringBuilder dips = new StringBuilder(); StringBuilder line = new StringBuilder();
            for (int i = 0; i < env.Count; i++)
            {
                double d = env[i] - med;
                line.Append(d < -20 ? '_' : d < -10 ? '.' : d < -4 ? '-' : '#');
                if (d < -10) dips.Append(et[i].ToString("0.000") + "(" + d.ToString("0") + "dB) ");
            }
            L("  envelope 25ms/char (# near median, - >4dB down, . >10dB, _ >20dB): " + line);
            L("  dips >10 dB below median " + med.ToString("0.0") + " dB: " + (dips.Length == 0 ? "none" : dips.ToString()));
        }
        L("  audible " + (total > 0 ? (100 * sound / total).ToString("0") : "?") + "% of the run; expected audio per play at this pitch = " + (lenSec / ratio).ToString("0.000") + " s");
        bins.Clear();
    }

    public static string Run(string audioDir, string cases)
    {
        Init();
        StartCapture();
        Thread.Sleep(300);
        PumpCapture();
        double bg = 0; int nb = 0;
        foreach (Bin b in bins) { bg = Math.Max(bg, b.rms); nb++; }
        L("background before the test: peak rms " + bg.ToString("0.00000") + " over " + nb + " bins");
        bins.Clear();
        foreach (string c in cases.Split(';'))
        {
            string[] p = c.Split(',');
            byte[] wav = File.ReadAllBytes(Path.Combine(audioDir, p[0]));
            RunCase(p[0], wav, double.Parse(p[1], System.Globalization.CultureInfo.InvariantCulture), double.Parse(p[2], System.Globalization.CultureInfo.InvariantCulture), p.Length > 3 ? int.Parse(p[3]) : 0);
            Thread.Sleep(400);
        }
        return log.ToString();
    }
}
