package dev.mtc;

import android.content.Context;
import android.graphics.Bitmap;
import android.graphics.Canvas;
import android.graphics.Matrix;
import android.graphics.Paint;
import android.graphics.RectF;
import android.view.GestureDetector;
import android.view.MotionEvent;
import android.view.ScaleGestureDetector;
import android.view.View;

/** A picture you can pinch, drag and double-tap, fitted on first layout. */
public class ZoomView extends View {
    private final Paint paint = new Paint(Paint.FILTER_BITMAP_FLAG);
    private final Matrix matrix = new Matrix();
    private final RectF bounds = new RectF();
    private Bitmap bitmap;
    private float scale = 1f;
    private float minScale = 1f;
    private float maxScale = 8f;
    private float baseX, baseY;
    private final ScaleGestureDetector zoom;
    private final GestureDetector taps;

    public ZoomView(Context context) {
        super(context);
        setBackgroundColor(0xFF000000);
        zoom = new ScaleGestureDetector(context, new ScaleGestureDetector.SimpleOnScaleGestureListener() {
            @Override
            public boolean onScale(ScaleGestureDetector d) {
                applyScale(d.getScaleFactor(), d.getFocusX(), d.getFocusY());
                return true;
            }
        });
        taps = new GestureDetector(context, new GestureDetector.SimpleOnGestureListener() {
            @Override
            public boolean onDoubleTap(MotionEvent e) {
                if (scale > minScale * 1.05f) {
                    fit();
                } else {
                    applyScaleRelative(2.5f, e.getX(), e.getY());
                }
                return true;
            }

            @Override
            public boolean onScroll(MotionEvent a, MotionEvent b, float dx, float dy) {
                if (a != null && a.getPointerCount() > 1) {
                    return false;
                }
                matrix.postTranslate(-dx, -dy);
                clampPan();
                invalidate();
                return true;
            }
        });
    }

    public void setBitmap(Bitmap bmp) {
        bitmap = bmp;
        requestLayout();
        fit();
    }

    public Bitmap getBitmap() {
        return bitmap;
    }

    private void fit() {
        if (bitmap == null || getWidth() == 0 || getHeight() == 0) {
            return;
        }
        float sx = (float) getWidth() / bitmap.getWidth();
        float sy = (float) getHeight() / bitmap.getHeight();
        minScale = Math.min(sx, sy);
        maxScale = Math.max(minScale * 8f, 8f);
        scale = minScale;
        matrix.reset();
        matrix.postScale(scale, scale);
        baseX = (getWidth() - bitmap.getWidth() * scale) / 2f;
        baseY = (getHeight() - bitmap.getHeight() * scale) / 2f;
        matrix.postTranslate(baseX, baseY);
        invalidate();
    }

    private void applyScale(float factor, float focusX, float focusY) {
        applyScaleRelative(factor, focusX, focusY);
    }

    private void applyScaleRelative(float factor, float focusX, float focusY) {
        if (bitmap == null) {
            return;
        }
        float next = Math.max(minScale, Math.min(maxScale, scale * factor));
        float real = next / scale;
        scale = next;
        matrix.postScale(real, real, focusX, focusY);
        clampPan();
        invalidate();
    }

    private void clampPan() {
        if (bitmap == null) {
            return;
        }
        bounds.set(0, 0, bitmap.getWidth(), bitmap.getHeight());
        matrix.mapRect(bounds);
        float dx = 0;
        float dy = 0;
        float w = getWidth();
        float h = getHeight();
        if (bounds.width() <= w) {
            dx = (w - bounds.width()) / 2f - bounds.left;
        } else if (bounds.left > 0) {
            dx = -bounds.left;
        } else if (bounds.right < w) {
            dx = w - bounds.right;
        }
        if (bounds.height() <= h) {
            dy = (h - bounds.height()) / 2f - bounds.top;
        } else if (bounds.top > 0) {
            dy = -bounds.top;
        } else if (bounds.bottom < h) {
            dy = h - bounds.bottom;
        }
        if (dx != 0 || dy != 0) {
            matrix.postTranslate(dx, dy);
        }
    }

    @Override
    protected void onSizeChanged(int w, int h, int ow, int oh) {
        super.onSizeChanged(w, h, ow, oh);
        fit();
    }

    @Override
    protected void onDraw(Canvas canvas) {
        if (bitmap != null) {
            canvas.drawBitmap(bitmap, matrix, paint);
        }
    }

    @Override
    public boolean onTouchEvent(MotionEvent event) {
        zoom.onTouchEvent(event);
        taps.onTouchEvent(event);
        return true;
    }
}
