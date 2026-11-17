package dev.mtc;

import android.Manifest;
import android.app.Activity;
import android.content.Context;
import android.content.pm.PackageManager;
import android.graphics.ImageFormat;
import android.graphics.SurfaceTexture;
import android.hardware.camera2.CameraAccessException;
import android.hardware.camera2.CameraCaptureSession;
import android.hardware.camera2.CameraCharacteristics;
import android.hardware.camera2.CameraDevice;
import android.hardware.camera2.CameraManager;
import android.hardware.camera2.CaptureRequest;
import android.hardware.camera2.params.StreamConfigurationMap;
import android.media.Image;
import android.media.ImageReader;
import android.os.Bundle;
import android.os.Handler;
import android.os.HandlerThread;
import android.os.Looper;
import android.util.Size;
import android.view.Gravity;
import android.view.Surface;
import android.view.TextureView;
import android.view.View;
import android.view.ViewGroup;
import android.widget.FrameLayout;
import android.widget.TextView;
import android.widget.Toast;

import java.io.File;
import java.nio.ByteBuffer;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.Comparator;
import java.util.List;
import java.util.Locale;

/**
 * The camera: Camera2 preview, one still at a time, encoded straight to `.mtc`.
 *
 * <p>The still arrives as {@code YUV_420_888}, so no JPEG is ever produced: the
 * planes are copied out and the conversion plus coding happen in Rust. A large
 * sensor frame takes a moment on a phone, so the work runs on a worker thread
 * and the header line reports the time it took.
 */
public class CameraActivity extends Activity {
    private static final int REQ_CAMERA = 1;
    /** Above this many pixels the still is captured smaller, to keep it snappy. */
    private static final int MAX_PIXELS = 4000 * 3000;

    private final Handler ui = new Handler(Looper.getMainLooper());
    private HandlerThread worker;
    private Handler cameraHandler;

    private FrameLayout root;
    private TextureView preview;
    private TextView hud;
    private CameraDevice device;
    private CameraCaptureSession session;
    private ImageReader stills;
    private Size stillSize = new Size(1920, 1080);
    private String cameraId;
    private boolean busy;
    private final int quality = 88;

    @Override
    protected void onCreate(Bundle state) {
        super.onCreate(state);

        root = new FrameLayout(this);
        root.setBackgroundColor(0xFF000000);

        preview = new TextureView(this);
        root.addView(preview, new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));

        hud = new TextView(this);
        hud.setTextColor(0xFFEDEDF0);
        hud.setTextSize(12);
        hud.setPadding(dp(16), dp(14), dp(16), dp(14));
        hud.setBackgroundColor(0x66000000);
        root.addView(hud, new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT,
                Gravity.TOP));

        TextView shutter = new TextView(this);
        shutter.setText("●");
        shutter.setTextColor(0xFFFFFFFF);
        shutter.setTextSize(44);
        shutter.setGravity(Gravity.CENTER);
        shutter.setBackgroundColor(0x33FFFFFF);
        FrameLayout.LayoutParams lp = new FrameLayout.LayoutParams(dp(92), dp(92),
                Gravity.BOTTOM | Gravity.CENTER_HORIZONTAL);
        lp.setMargins(0, 0, 0, dp(28));
        root.addView(shutter, lp);
        shutter.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                capture();
            }
        });

        TextView close = new TextView(this);
        close.setText("✕");
        close.setTextColor(0xFFFFFFFF);
        close.setTextSize(22);
        close.setGravity(Gravity.CENTER);
        FrameLayout.LayoutParams blp = new FrameLayout.LayoutParams(dp(48), dp(48),
                Gravity.TOP | Gravity.END);
        blp.setMargins(0, dp(56), dp(16), 0);
        root.addView(close, blp);
        close.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                finish();
            }
        });

        setContentView(root);

        worker = new HandlerThread("mtc-camera");
        worker.start();
        cameraHandler = new Handler(worker.getLooper());

        preview.setSurfaceTextureListener(new TextureView.SurfaceTextureListener() {
            @Override
            public void onSurfaceTextureAvailable(SurfaceTexture surface, int width, int height) {
                openCamera();
            }

            @Override
            public void onSurfaceTextureSizeChanged(SurfaceTexture surface, int width, int height) {
            }

            @Override
            public boolean onSurfaceTextureDestroyed(SurfaceTexture surface) {
                return true;
            }

            @Override
            public void onSurfaceTextureUpdated(SurfaceTexture surface) {
            }
        });

        if (checkSelfPermission(Manifest.permission.CAMERA) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(new String[]{Manifest.permission.CAMERA}, REQ_CAMERA);
        }
    }

    @Override
    public void onRequestPermissionsResult(int code, String[] permissions, int[] results) {
        super.onRequestPermissionsResult(code, permissions, results);
        if (code == REQ_CAMERA
                && (results.length == 0 || results[0] != PackageManager.PERMISSION_GRANTED)) {
            Toast.makeText(this, "没有相机权限", Toast.LENGTH_LONG).show();
            finish();
        }
    }

    private void openCamera() {
        if (checkSelfPermission(Manifest.permission.CAMERA) != PackageManager.PERMISSION_GRANTED) {
            return;
        }
        CameraManager manager = (CameraManager) getSystemService(Context.CAMERA_SERVICE);
        try {
            cameraId = pickBackCamera(manager);
            if (cameraId == null) {
                Toast.makeText(this, "找不到相机", Toast.LENGTH_LONG).show();
                return;
            }
            CameraCharacteristics chars = manager.getCameraCharacteristics(cameraId);
            StreamConfigurationMap map =
                    chars.get(CameraCharacteristics.SCALER_STREAM_CONFIGURATION_MAP);
            stillSize = pickStillSize(map);
            stills = ImageReader.newInstance(stillSize.getWidth(), stillSize.getHeight(),
                    ImageFormat.YUV_420_888, 2);
            stills.setOnImageAvailableListener(new ImageReader.OnImageAvailableListener() {
                @Override
                public void onImageAvailable(ImageReader reader) {
                    onStill(reader);
                }
            }, cameraHandler);

            applyPreviewAspect();
            manager.openCamera(cameraId, new CameraDevice.StateCallback() {
                @Override
                public void onOpened(CameraDevice camera) {
                    device = camera;
                    startPreview();
                }

                @Override
                public void onDisconnected(CameraDevice camera) {
                    camera.close();
                    device = null;
                }

                @Override
                public void onError(CameraDevice camera, final int error) {
                    camera.close();
                    device = null;
                    ui.post(new Runnable() {
                        @Override
                        public void run() {
                            hud.setText("相机出错 " + error);
                        }
                    });
                }
            }, cameraHandler);
        } catch (CameraAccessException e) {
            Toast.makeText(this, "打不开相机：" + e.getMessage(), Toast.LENGTH_LONG).show();
        } catch (SecurityException e) {
            Toast.makeText(this, "没有相机权限", Toast.LENGTH_LONG).show();
        }
    }

    private String pickBackCamera(CameraManager manager) throws CameraAccessException {
        String fallback = null;
        String[] ids = manager.getCameraIdList();
        for (int i = 0; i < ids.length; i++) {
            String id = ids[i];
            CameraCharacteristics chars = manager.getCameraCharacteristics(id);
            Integer facing = chars.get(CameraCharacteristics.LENS_FACING);
            if (facing != null && facing.intValue() == CameraCharacteristics.LENS_FACING_BACK) {
                return id;
            }
            if (fallback == null) {
                fallback = id;
            }
        }
        return fallback;
    }

    private Size pickStillSize(StreamConfigurationMap map) {
        Size[] sizes = map == null ? null : map.getOutputSizes(ImageFormat.YUV_420_888);
        if (sizes == null || sizes.length == 0) {
            return new Size(1920, 1080);
        }
        List<Size> candidates = new ArrayList<Size>(Arrays.asList(sizes));
        Collections.sort(candidates, new Comparator<Size>() {
            @Override
            public int compare(Size a, Size b) {
                return Long.compare((long) b.getWidth() * b.getHeight(),
                        (long) a.getWidth() * a.getHeight());
            }
        });
        for (int i = 0; i < candidates.size(); i++) {
            Size s = candidates.get(i);
            if ((long) s.getWidth() * s.getHeight() <= MAX_PIXELS) {
                return s;
            }
        }
        return candidates.get(candidates.size() - 1);
    }

    /** Match the preview window to the sensor aspect so faces are not stretched. */
    private void applyPreviewAspect() {
        int vw = root.getWidth();
        int vh = root.getHeight();
        if (vw == 0 || vh == 0) {
            root.post(new Runnable() {
                @Override
                public void run() {
                    applyPreviewAspect();
                }
            });
            return;
        }
        float target = (float) stillSize.getWidth() / (float) stillSize.getHeight();
        float view = (float) vw / (float) vh;
        int w;
        int h;
        if (target > view) {
            w = vw;
            h = Math.round(vw / target);
        } else {
            h = vh;
            w = Math.round(vh * target);
        }
        preview.setLayoutParams(new FrameLayout.LayoutParams(w, h, Gravity.CENTER));
    }

    private void startPreview() {
        if (device == null || !preview.isAvailable()) {
            return;
        }
        try {
            SurfaceTexture texture = preview.getSurfaceTexture();
            texture.setDefaultBufferSize(stillSize.getWidth(), stillSize.getHeight());
            Surface surface = new Surface(texture);
            final CaptureRequest.Builder builder =
                    device.createCaptureRequest(CameraDevice.TEMPLATE_PREVIEW);
            builder.addTarget(surface);
            builder.set(CaptureRequest.CONTROL_MODE, CaptureRequest.CONTROL_MODE_AUTO);

            List<Surface> targets = new ArrayList<Surface>();
            targets.add(surface);
            targets.add(stills.getSurface());
            device.createCaptureSession(targets, new CameraCaptureSession.StateCallback() {
                @Override
                public void onConfigured(CameraCaptureSession configured) {
                    session = configured;
                    try {
                        session.setRepeatingRequest(builder.build(), null, cameraHandler);
                        ui.post(new Runnable() {
                            @Override
                            public void run() {
                                hud.setText(String.format(Locale.US,
                                        "%d×%d · q%d · 直接写 .mtc",
                                        stillSize.getWidth(), stillSize.getHeight(), quality));
                            }
                        });
                    } catch (CameraAccessException e) {
                        final String msg = e.getMessage();
                        ui.post(new Runnable() {
                            @Override
                            public void run() {
                                hud.setText("预览失败：" + msg);
                            }
                        });
                    }
                }

                @Override
                public void onConfigureFailed(CameraCaptureSession failed) {
                    ui.post(new Runnable() {
                        @Override
                        public void run() {
                            hud.setText("预览配置失败");
                        }
                    });
                }
            }, cameraHandler);
        } catch (CameraAccessException e) {
            final String msg = e.getMessage();
            ui.post(new Runnable() {
                @Override
                public void run() {
                    hud.setText("预览出错：" + msg);
                }
            });
        }
    }

    private void capture() {
        if (busy || device == null || session == null) {
            return;
        }
        busy = true;
        hud.setText("拍摄中…");
        try {
            CaptureRequest.Builder builder =
                    device.createCaptureRequest(CameraDevice.TEMPLATE_STILL_CAPTURE);
            builder.addTarget(stills.getSurface());
            builder.set(CaptureRequest.CONTROL_MODE, CaptureRequest.CONTROL_MODE_AUTO);
            session.capture(builder.build(), null, cameraHandler);
        } catch (CameraAccessException e) {
            busy = false;
            hud.setText("拍摄失败：" + e.getMessage());
        }
    }

    /** ImageReader callback: copy the planes out, encode, save. */
    private void onStill(ImageReader reader) {
        Image image = reader.acquireNextImage();
        if (image == null) {
            return;
        }
        if (image.getFormat() != ImageFormat.YUV_420_888) {
            image.close();
            return;
        }
        final long start = System.currentTimeMillis();
        final int w = image.getWidth();
        final int h = image.getHeight();
        byte[] blob = null;
        try {
            Image.Plane[] planes = image.getPlanes();
            byte[] y = copy(planes[0]);
            byte[] u = copy(planes[1]);
            byte[] v = copy(planes[2]);
            int yStride = planes[0].getRowStride();
            int uvStride = planes[1].getRowStride();
            int uvPixel = planes[1].getPixelStride();
            blob = Mtc.encodeYuv(y, u, v, w, h, yStride, uvStride, uvPixel, quality);
        } catch (RuntimeException e) {
            blob = null;
        } finally {
            image.close();
        }
        final byte[] encoded = blob;
        final long ms = System.currentTimeMillis() - start;
        if (encoded == null) {
            ui.post(new Runnable() {
                @Override
                public void run() {
                    busy = false;
                    hud.setText("编码失败");
                }
            });
            return;
        }
        final File out = Store.nextPhoto(this);
        final boolean ok = Store.write(out, encoded);
        ui.post(new Runnable() {
            @Override
            public void run() {
                busy = false;
                if (ok) {
                    hud.setText(String.format(Locale.US, "%d×%d · %s · %d ms · q%d",
                            w, h, Store.human(encoded.length), ms, quality));
                } else {
                    hud.setText("写文件失败");
                }
                Toast.makeText(CameraActivity.this,
                        ok ? "已保存 " + Store.human(encoded.length) : "保存失败",
                        Toast.LENGTH_SHORT).show();
            }
        });
    }

    private static byte[] copy(Image.Plane plane) {
        ByteBuffer buffer = plane.getBuffer();
        buffer.rewind();
        byte[] out = new byte[buffer.remaining()];
        buffer.get(out);
        return out;
    }

    @Override
    protected void onResume() {
        super.onResume();
        if (device == null && preview.isAvailable()) {
            openCamera();
        }
    }

    @Override
    protected void onPause() {
        super.onPause();
        closeCamera();
    }

    @Override
    protected void onDestroy() {
        super.onDestroy();
        closeCamera();
        if (worker != null) {
            worker.quitSafely();
        }
    }

    private void closeCamera() {
        if (session != null) {
            session.close();
            session = null;
        }
        if (device != null) {
            device.close();
            device = null;
        }
        if (stills != null) {
            stills.close();
            stills = null;
        }
    }

    private int dp(int v) {
        return Math.round(v * getResources().getDisplayMetrics().density);
    }
}
