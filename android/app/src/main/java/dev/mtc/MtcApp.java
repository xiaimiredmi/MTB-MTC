package dev.mtc;

import android.app.Application;

import java.io.File;
import java.io.FileOutputStream;
import java.io.PrintWriter;
import java.io.StringWriter;
import java.text.SimpleDateFormat;
import java.util.Date;
import java.util.Locale;

/**
 * Writes any uncaught Java crash to a file the user (or a PC over USB) can read.
 *
 * <p>The app is tested on phones that are nowhere near the machine it was built
 * on, so a crash that only says "it closed" is useless. This turns it into a
 * stack trace in {@code Android/data/dev.mtc/files/crash.txt}. Native crashes
 * still need logcat; this covers everything the JVM sees.
 */
public class MtcApp extends Application {
    @Override
    public void onCreate() {
        super.onCreate();
        final Thread.UncaughtExceptionHandler previous =
                Thread.getDefaultUncaughtExceptionHandler();
        Thread.setDefaultUncaughtExceptionHandler(new Thread.UncaughtExceptionHandler() {
            @Override
            public void uncaughtException(Thread thread, Throwable error) {
                write(error, thread);
                if (previous != null) {
                    previous.uncaughtException(thread, error);
                }
            }
        });
        // Load the codec now: a missing or mismatched library is then a clean,
        // logged failure instead of a surprise when the shutter is pressed.
        try {
            Mtc.warmUp();
        } catch (Throwable t) {
            write(t, Thread.currentThread());
        }
    }

    private void write(Throwable error, Thread thread) {
        StringWriter text = new StringWriter();
        text.write("time    " + new SimpleDateFormat("yyyy-MM-dd HH:mm:ss", Locale.US)
                .format(new Date()) + "\n");
        text.write("thread  " + thread.getName() + "\n");
        text.write("abi     " + android.os.Build.SUPPORTED_ABIS[0] + "\n");
        text.write("device  " + android.os.Build.MANUFACTURER + " " + android.os.Build.MODEL
                + " / Android " + android.os.Build.VERSION.RELEASE + "\n\n");
        PrintWriter writer = new PrintWriter(text);
        error.printStackTrace(writer);
        writer.flush();
        try {
            File dir = getExternalFilesDir(null);
            if (dir == null) {
                dir = getFilesDir();
            }
            FileOutputStream out = new FileOutputStream(new File(dir, "crash.txt"), true);
            try {
                out.write(text.toString().getBytes("UTF-8"));
                out.write('\n');
            } finally {
                out.close();
            }
        } catch (Throwable ignored) {
            // nothing useful to do if even this fails
        }
    }
}
