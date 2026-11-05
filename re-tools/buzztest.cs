// buzztest.cs - the rotary buzzer (crdrive.dll buzz.rs) on the REAL 32-bit DirectSound, measured by WASAPI
// loopback: the harness makes its own IDirectSound8 (the game hands crdrive its CAudioManager's), calls the DLL's
// cr_buzz_test(ds, 2/0) (2 = heard without the window focus, which a harness never has) and checks that the tone plays at 2450 Hz while on, stops when off, and starts again.
// Plays audibly (~1.2 s in all). Run with buzztest.ps1 (32-bit Windows PowerShell).
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading;

public static class BuzzTest
{
    [UnmanagedFunctionPointer(CallingConvention.StdCall)] delegate int F0(IntPtr t);
    [UnmanagedFunctionPointer(CallingConvention.StdCall)] delegate int F1i(IntPtr t, int a);
    [UnmanagedFunctionPointer(CallingConvention.StdCall)] delegate int FCoop(IntPtr t, IntPtr hwnd, int level);
    [UnmanagedFunctionPointer(CallingConvention.StdCall)] delegate int FoutI(IntPtr t, out int a);
    [UnmanagedFunctionPointer(CallingConvention.StdCall)] delegate int FGetDefEp(IntPtr t, int flow, int role, out IntPtr dev);
    [UnmanagedFunctionPointer(CallingConvention.StdCall)] delegate int FActivate(IntPtr t, ref Guid iid, int ctx, IntPtr p, out IntPtr ppv);
    [UnmanagedFunctionPointer(CallingConvention.StdCall)] delegate int FInit(IntPtr t, int share, int flags, long dur, long per, IntPtr fmt, IntPtr sess);
    [UnmanagedFunctionPointer(CallingConvention.StdCall)] delegate int FGetService(IntPtr t, ref Guid iid, out IntPtr ppv);
    [UnmanagedFunctionPointer(CallingConvention.StdCall)] delegate int FGetMix(IntPtr t, out IntPtr fmt);
    [UnmanagedFunctionPointer(CallingConvention.StdCall)] delegate int FGetBuffer(IntPtr t, out IntPtr data, out int frames, out int flags, out long devpos, out long qpc);
    [UnmanagedFunctionPointer(CallingConvention.Cdecl)] delegate uint FBuzz(uint ds, uint on);

    [DllImport("ole32.dll")] static extern int CoInitialize(IntPtr p);
    [DllImport("ole32.dll")] static extern int CoCreateInstance(ref Guid clsid, IntPtr outer, int ctx, ref Guid iid, out IntPtr ppv);
    [DllImport("dsound.dll")] static extern int DirectSoundCreate8(IntPtr guid, out IntPtr ds, IntPtr outer);
    [DllImport("user32.dll")] static extern IntPtr GetDesktopWindow();
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode)] static extern IntPtr LoadLibraryW(string p);
    [DllImport("kernel32.dll", CharSet = CharSet.Ansi)] static extern IntPtr GetProcAddress(IntPtr h, string n);

    static T D<T>(IntPtr obj, int slot) where T : class
    {
        IntPtr vt = Marshal.ReadIntPtr(obj);
        return Marshal.GetDelegateForFunctionPointer(Marshal.ReadIntPtr(vt, slot * 4), typeof(T)) as T;
    }
    static void Ck(int hr, string what) { if (hr < 0) throw new Exception(what + " failed hr=0x" + hr.ToString("x8")); }

    static Guid CLSID_MMDevEnum = new Guid("BCDE0395-E52F-467C-8E3D-C4579291692E");
    static Guid IID_MMDevEnum = new Guid("A95664D2-9614-4F35-A746-DE8DB63617E6");
    static Guid IID_AudioClient = new Guid("1CB9AD4C-DBFA-4c32-B178-C2F568A703B2");
    static Guid IID_CaptureClient = new Guid("C8ADBD64-E71E-48a0-A4DE-185C395CD317");

    static IntPtr capture;
    static int ch, rate;
    static List<float> samples = new List<float>();
    static StringBuilder log = new StringBuilder();
    static void L(string s) { log.AppendLine(s); Console.WriteLine(s); }

    static void StartCapture()
    {
        IntPtr en, dev, ac, fmt;
        Ck(CoCreateInstance(ref CLSID_MMDevEnum, IntPtr.Zero, 0x17, ref IID_MMDevEnum, out en), "MMDeviceEnumerator");
        Ck(D<FGetDefEp>(en, 4)(en, 0, 0, out dev), "GetDefaultAudioEndpoint");
        Ck(D<FActivate>(dev, 3)(dev, ref IID_AudioClient, 0x17, IntPtr.Zero, out ac), "Activate");
        Ck(D<FGetMix>(ac, 8)(ac, out fmt), "GetMixFormat");
        ch = Marshal.ReadInt16(fmt, 2);
        rate = Marshal.ReadInt32(fmt, 4);
        int bits = Marshal.ReadInt16(fmt, 14);
        if (bits != 32) throw new Exception("loopback mix format is not 32-bit float (" + bits + " bits)");
        Ck(D<FInit>(ac, 3)(ac, 0, 0x20000, 10000000L, 0L, fmt, IntPtr.Zero), "IAudioClient.Initialize(loopback)");
        Ck(D<FGetService>(ac, 14)(ac, ref IID_CaptureClient, out capture), "GetService(capture)");
        Ck(D<F0>(ac, 10)(ac), "Start");
    }

    // pump for ms milliseconds, keep channel 0
    static List<float> Record(int ms)
    {
        samples = new List<float>();
        DateTime end = DateTime.Now.AddMilliseconds(ms);
        while (DateTime.Now < end)
        {
            Thread.Sleep(5);
            while (true)
            {
                int n;
                if (D<FoutI>(capture, 5)(capture, out n) < 0 || n == 0) break;
                IntPtr p; int frames, flags; long devpos, qpc;
                if (D<FGetBuffer>(capture, 3)(capture, out p, out frames, out flags, out devpos, out qpc) < 0) break;
                float[] buf = new float[frames * ch];
                if ((flags & 2) == 0) Marshal.Copy(p, buf, 0, buf.Length);
                for (int f = 0; f < frames; f++) samples.Add(buf[f * ch]);
                D<F1i>(capture, 4)(capture, frames);
            }
        }
        return samples;
    }

    // the amplitude at frequency hz (Goertzel) over the middle of a recording: other sounds playing on the PC
    // (music, video) do not count, only the buzzer's tone
    static double Tone(List<float> s, double hz)
    {
        int a = s.Count / 4, b = s.Count * 3 / 4, n = Math.Max(1, b - a);
        double w = 2 * Math.PI * hz / rate, c = 2 * Math.Cos(w), s1 = 0, s2 = 0;
        for (int i = a; i < b; i++)
        {
            double s0 = s[i] + c * s1 - s2;
            s2 = s1; s1 = s0;
        }
        return 2 * Math.Sqrt(Math.Max(0, s1 * s1 + s2 * s2 - c * s1 * s2)) / n;
    }

    // (amplitude at 2450 Hz, the strongest of 2300..2600 Hz in 10 Hz steps)
    static double[] Measure(List<float> s)
    {
        double best = 0, at = 0;
        for (double hz = 2300; hz <= 2600; hz += 10)
        {
            double t = Tone(s, hz);
            if (t > best) { best = t; at = hz; }
        }
        return new double[] { Tone(s, 2450), at };
    }

    public static string Run(string dll)
    {
        CoInitialize(IntPtr.Zero);
        IntPtr h = LoadLibraryW(dll);
        if (h == IntPtr.Zero) throw new Exception("LoadLibrary " + dll);
        FBuzz buzz = Marshal.GetDelegateForFunctionPointer(GetProcAddress(h, "cr_buzz_test"), typeof(FBuzz)) as FBuzz;
        IntPtr ds;
        Ck(DirectSoundCreate8(IntPtr.Zero, out ds, IntPtr.Zero), "DirectSoundCreate8");
        Ck(D<FCoop>(ds, 6)(ds, GetDesktopWindow(), 2), "SetCooperativeLevel(PRIORITY)");
        StartCapture();
        L("loopback: " + ch + " ch, " + rate + " Hz");
        double[] quiet = Measure(Record(250));
        uint b1 = buzz((uint)ds.ToInt32(), 2);
        double[] on1 = Measure(Record(400));
        uint b0 = buzz((uint)ds.ToInt32(), 0);
        Record(60); // the stop's tail
        double[] off = Measure(Record(250));
        uint b2 = buzz((uint)ds.ToInt32(), 2);
        double[] on2 = Measure(Record(300));
        buzz((uint)ds.ToInt32(), 0);
        L(string.Format("before: 2450 Hz amplitude {0:F5}", quiet[0]));
        L(string.Format("on:     2450 Hz amplitude {0:F5}, peak at {1:F0} Hz  (buffer 0x{2:x})", on1[0], on1[1], b1));
        L(string.Format("off:    2450 Hz amplitude {0:F5}  (returned 0x{1:x})", off[0], b0));
        L(string.Format("again:  2450 Hz amplitude {0:F5}, peak at {1:F0} Hz  (buffer 0x{2:x})", on2[0], on2[1], b2));
        bool ok = b1 != 0 && b0 == 0 && b2 == b1
                  && on1[0] > 10 * Math.Max(quiet[0], 1e-5) && Math.Abs(on1[1] - 2450) <= 20
                  && off[0] < on1[0] / 10 && on2[0] > on1[0] / 2 && Math.Abs(on2[1] - 2450) <= 20;
        L(ok ? "BUZZER OK" : "BUZZER FAILED");
        return log.ToString();
    }
}
