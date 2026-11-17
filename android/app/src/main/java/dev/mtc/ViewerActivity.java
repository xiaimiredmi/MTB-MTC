package dev.mtc;

import android.app.Activity;
import android.content.ContentValues;
import android.graphics.Bitmap;
import android.net.Uri;
import android.os.Build;
import android.os.Environment;
import android.provider.MediaStore;
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
    private File current;

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

        TextView export = new TextView(this);
        export.setText("导出 PNG");
        export.setTextColor(0xFFF2F2F4);
        export.setTextSize(13);
        export.setPadding(dp(14), 0, 0, 0);
        bar.addView(export);
        export.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                exportPng();
            }
        });
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
        current = new File(path);
        open(current);
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

    /**
     * Write the picture out as a PNG.
     *
     * <p>Without this the photos are trapped: only this app reads .mtc. On
     * Android 10 and later the PNG goes into the system gallery under
     * `Pictures/MTC`, so other apps can see it; on older versions it lands next to
     * the .mtc files, which is visible over USB.
     */
    private void exportPng() {
        Bitmap bmp = zoom.getBitmap();
        if (bmp == null) {
            Toast.makeText(this, "还没有解出图片", Toast.LENGTH_SHORT).show();
            return;
        }
        final String name = current == null ? "export" : current.getName();
        final Bitmap copy = bmp;
        status.setText("导出中…");
        new Thread(new Runnable() {
            @Override
            public void run() {
                String base = name.replaceAll("\\.mtc$", "");
                String where = null;
                // Preferred: hand it to the system gallery.
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                    try {
                        ContentValues values = new ContentValues();
                        values.put(MediaStore.Images.Media.DISPLAY_NAME, base + ".png");
                        values.put(MediaStore.Images.Media.MIME_TYPE, "image/png");
                        values.put(MediaStore.Images.Media.RELATIVE_PATH,
                                Environment.DIRECTORY_PICTURES + "/MTC");
                        Uri target = getContentResolver().insert(
                                MediaStore.Images.Media.EXTERNAL_CONTENT_URI, values);
                        if (target != null) {
                            java.io.OutputStream os =
                                    getContentResolver().openOutputStream(target);
                            try {
                                if (os != null && copy.compress(Bitmap.CompressFormat.PNG, 100, os)) {
                                    where = "相册 Pictures/MTC/" + base + ".png";
                                }
                            } finally {
                                if (os != null) {
                                    os.close();
                                }
                            }
                        }
                    } catch (Exception e) {
                        where = null;
                    }
                }
                // Fallback (and the only path before Android 10): app folder.
                if (where == null) {
                    File out = new File(Store.dir(ViewerActivity.this), base + ".png");
                    try {
                        FileOutputStream fos = new FileOutputStream(out);
                        try {
                            if (copy.compress(Bitmap.CompressFormat.PNG, 100, fos)) {
                                where = out.getAbsolutePath();
                            }
                        } finally {
                            fos.close();
                        }
                    } catch (Exception e) {
                        where = null;
                    }
                }
                final String landed = where;
                ui.post(new Runnable() {
                    @Override
                    public void run() {
                        status.setText(landed == null ? "导出失败" : "已导出 " + landed);
                        Toast.makeText(ViewerActivity.this,
                                landed == null ? "导出失败" : "已导出 PNG",
                                Toast.LENGTH_SHORT).show();
                    }
                });
            }
        }, "mtc-export").start();
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
