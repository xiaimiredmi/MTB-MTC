package dev.mtc;

import android.app.Activity;
import android.graphics.Bitmap;
import android.net.Uri;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.view.Gravity;
import android.view.View;
import android.widget.FrameLayout;
import android.widget.LinearLayout;
import android.widget.TextView;
import android.widget.Toast;

import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.util.Locale;

/** One picture, full screen, pinch to zoom. Also the VIEW handler for .mtc. */
public class ViewerActivity extends Activity {
    public static final String EXTRA_PATH = "path";

    private final Handler ui = new Handler(Looper.getMainLooper());
    private ZoomView zoom;
    private TextView status;

    @Override
    protected void onCreate(Bundle state) {
        super.onCreate(state);

        FrameLayout root = new FrameLayout(this);
        root.setBackgroundColor(0xFF000000);
        zoom = new ZoomView(this);
        root.addView(zoom, new FrameLayout.LayoutParams(
                FrameLayout.LayoutParams.MATCH_PARENT, FrameLayout.LayoutParams.MATCH_PARENT));

        LinearLayout bar = new LinearLayout(this);
        bar.setOrientation(LinearLayout.HORIZONTAL);
        bar.setBackgroundColor(0xCC1B1B1F);
        bar.setPadding(dp(16), dp(12), dp(16), dp(12));

        TextView back = new TextView(this);
        back.setText("← 返回");
        back.setTextColor(0xFFF2F2F4);
        back.setTextSize(15);
        back.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                finish();
            }
        });
        bar.addView(back);

        status = new TextView(this);
        status.setTextColor(0xFFB9B9C0);
        status.setTextSize(12);
        status.setPadding(dp(16), 0, 0, 0);
        bar.addView(status, new LinearLayout.LayoutParams(0,
                LinearLayout.LayoutParams.WRAP_CONTENT, 1f));
        root.addView(bar, new FrameLayout.LayoutParams(
                FrameLayout.LayoutParams.MATCH_PARENT, FrameLayout.LayoutParams.WRAP_CONTENT,
                Gravity.TOP));

        setContentView(root);

        String path = getIntent().getStringExtra(EXTRA_PATH);
        if (path == null && getIntent().getData() != null) {
            path = importUri(getIntent().getData());
        }
        if (path == null) {
            Toast.makeText(this, "没有图片路径", Toast.LENGTH_SHORT).show();
            finish();
            return;
        }
        open(new File(path));
    }

    /** Content URIs arrive from other apps; copy into our own storage first. */
    private String importUri(Uri uri) {
        try {
            File out = Store.nextPhoto(this);
            InputStream in = getContentResolver().openInputStream(uri);
            if (in == null) {
                return null;
            }
            FileOutputStream fos = new FileOutputStream(out);
            byte[] buf = new byte[64 * 1024];
            int n;
            while ((n = in.read(buf)) > 0) {
                fos.write(buf, 0, n);
            }
            fos.close();
            in.close();
            return out.getAbsolutePath();
        } catch (Exception e) {
            return null;
        }
    }

    private void open(final File file) {
        status.setText(file.getName() + " · 解码中…");
        new Thread(new Runnable() {
            @Override
            public void run() {
                final byte[] data = Mtc.read(file);
                if (data == null) {
                    ui.post(new Runnable() {
                        @Override
                        public void run() {
                            status.setText(file.getName() + " · 读不出来");
                        }
                    });
                    return;
                }
                final String info = Mtc.info(data);
                final Bitmap bmp = Mtc.toBitmap(Mtc.decodeRgba(data, 0));
                ui.post(new Runnable() {
                    @Override
                    public void run() {
                        if (bmp == null) {
                            status.setText(file.getName() + " · 不是有效的 .mtc");
                            return;
                        }
                        zoom.setBitmap(bmp);
                        status.setText(String.format(Locale.US, "%s · %s · %s",
                                file.getName(),
                                info == null ? "" : info,
                                Store.human(file.length())));
                    }
                });
            }
        }, "mtc-decode").start();
    }

    @Override
    protected void onDestroy() {
        super.onDestroy();
        Bitmap bmp = zoom.getBitmap();
        if (bmp != null && !bmp.isRecycled()) {
            bmp.recycle();
        }
    }

    private int dp(int v) {
        return Math.round(v * getResources().getDisplayMetrics().density);
    }
}
