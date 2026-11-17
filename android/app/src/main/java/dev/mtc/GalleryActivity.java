package dev.mtc;

import android.app.Activity;
import android.content.Intent;
import android.graphics.Bitmap;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.util.LruCache;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.app.AlertDialog;
import android.widget.BaseAdapter;
import android.widget.Button;
import android.widget.FrameLayout;
import android.widget.GridView;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.TextView;
import android.widget.Toast;

import java.io.File;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/**
 * The launcher screen: a grid of the pictures this app has taken, and one button
 * to take another.
 *
 * <p>Thumbnails are decoded by the codec at a bounded size (the codec supports
 * decoding straight to a smaller picture, so a 12 MP file does not become a
 * 12 MP bitmap just to fill a cell), on a small thread pool, and kept in an
 * {@link LruCache} sized to an eighth of the heap.
 */
public class GalleryActivity extends Activity {
    private final ExecutorService pool = Executors.newFixedThreadPool(3);
    private final Handler ui = new Handler(Looper.getMainLooper());
    private final List<File> files = new ArrayList<>();
    private LruCache<String, Bitmap> cache;
    private GridView grid;
    private TextView stats;
    private Adapter adapter;

    @Override
    protected void onCreate(Bundle state) {
        super.onCreate(state);

        int cacheBytes = (int) (Runtime.getRuntime().maxMemory() / 8);
        cache = new LruCache<String, Bitmap>(cacheBytes) {
            @Override
            protected int sizeOf(String key, Bitmap value) {
                return value.getByteCount();
            }
        };

        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setBackgroundColor(0xFF111114);

        LinearLayout head = new LinearLayout(this);
        head.setOrientation(LinearLayout.VERTICAL);
        head.setPadding(dp(20), dp(18), dp(20), dp(10));
        TextView title = new TextView(this);
        title.setText("MTC 相册");
        title.setTextColor(0xFFF2F2F4);
        title.setTextSize(22);
        head.addView(title);
        stats = new TextView(this);
        stats.setTextColor(0xFF8C8C93);
        stats.setTextSize(12);
        stats.setPadding(0, dp(4), 0, 0);
        head.addView(stats);
        root.addView(head, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT));

        grid = new GridView(this);
        grid.setNumColumns(3);
        grid.setHorizontalSpacing(dp(2));
        grid.setVerticalSpacing(dp(2));
        grid.setPadding(dp(2), dp(2), dp(2), dp(2));
        grid.setBackgroundColor(0xFF111114);
        adapter = new Adapter();
        grid.setAdapter(adapter);
        grid.setOnItemClickListener(new android.widget.AdapterView.OnItemClickListener() {
            @Override
            public void onItemClick(android.widget.AdapterView<?> parent, View view, int position, long id) {
                Intent i = new Intent(GalleryActivity.this, ViewerActivity.class);
                i.putExtra(ViewerActivity.EXTRA_PATH, files.get(position).getAbsolutePath());
                startActivity(i);
            }
        });
        grid.setOnItemLongClickListener(new android.widget.AdapterView.OnItemLongClickListener() {
            @Override
            public boolean onItemLongClick(android.widget.AdapterView<?> parent, View view,
                                           final int position, long id) {
                final File file = files.get(position);
                new AlertDialog.Builder(GalleryActivity.this)
                        .setTitle(file.getName())
                        .setMessage(Store.human(file.length()) + "，要删除吗？")
                        .setNegativeButton("取消", null)
                        .setPositiveButton("删除", new android.content.DialogInterface.OnClickListener() {
                            @Override
                            public void onClick(android.content.DialogInterface d, int which) {
                                //noinspection ResultOfMethodCallIgnored
                                file.delete();
                                cache.remove(file.getAbsolutePath() + "@" + file.lastModified());
                                reload();
                            }
                        })
                        .show();
                return true;
            }
        });
        root.addView(grid, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f));

        FrameLayout bar = new FrameLayout(this);
        bar.setBackgroundColor(0xFF1B1B1F);
        Button shoot = new Button(this);
        shoot.setText("拍照");
        shoot.setAllCaps(false);
        shoot.setTextSize(15);
        FrameLayout.LayoutParams lp = new FrameLayout.LayoutParams(dp(140), dp(46),
                Gravity.CENTER);
        lp.setMargins(0, dp(10), 0, dp(10));
        bar.addView(shoot, lp);
        shoot.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                startActivity(new Intent(GalleryActivity.this, CameraActivity.class));
            }
        });
        root.addView(bar, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT));

        setContentView(root);
        Mtc.warmUp();
    }

    @Override
    protected void onResume() {
        super.onResume();
        reload();
    }

    private void reload() {
        files.clear();
        files.addAll(Store.list(this));
        adapter.notifyDataSetChanged();
        long bytes = Store.totalBytes(files);
        stats.setText(String.format(Locale.US, "%d 张 · %s · %s",
                files.size(), Store.human(bytes), Store.dir(this).getAbsolutePath()));
        if (files.isEmpty()) {
            Toast.makeText(this, "还没有照片，点下面的“拍照”", Toast.LENGTH_SHORT).show();
        }
    }

    @Override
    protected void onDestroy() {
        super.onDestroy();
        pool.shutdownNow();
    }

    private int dp(int v) {
        return Math.round(v * getResources().getDisplayMetrics().density);
    }

    private class Adapter extends BaseAdapter {
        @Override
        public int getCount() {
            return files.size();
        }

        @Override
        public Object getItem(int position) {
            return files.get(position);
        }

        @Override
        public long getItemId(int position) {
            return position;
        }

        @Override
        public View getView(int position, View reuse, ViewGroup parent) {
            ImageView view = reuse instanceof ImageView ? (ImageView) reuse : new ImageView(GalleryActivity.this);
            view.setScaleType(ImageView.ScaleType.CENTER_CROP);
            view.setBackgroundColor(0xFF1E1E22);
            File file = files.get(position);
            String key = file.getAbsolutePath() + "@" + file.lastModified();
            Bitmap cached = cache.get(key);
            view.setTag(key);
            if (cached != null) {
                view.setImageBitmap(cached);
                return view;
            }
            view.setImageDrawable(null);
            final int side = Math.max(120, parent.getWidth() / 3);
            final ImageView target = view;
            pool.execute(new Runnable() {
                @Override
                public void run() {
                    final Bitmap bmp = Mtc.thumbnail(file, side);
                    if (bmp == null) {
                        return;
                    }
                    cache.put(key, bmp);
                    ui.post(new Runnable() {
                        @Override
                        public void run() {
                            if (key.equals(target.getTag())) {
                                target.setImageBitmap(bmp);
                            }
                        }
                    });
                }
            });
            return view;
        }
    }
}
