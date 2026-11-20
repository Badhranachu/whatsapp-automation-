import { useEffect, useRef, useState } from 'react';
import { isValidPhone, PHONE_ERROR } from '../services/phone';
import { showError, showSuccess } from '../services/alerts';
import { Button, Card, inputClass, Spinner } from './ui';

const MAX_IMAGE_BYTES = 5 * 1024 * 1024;
const MAX_CAPTION = 1024;

// Shared phone-number form. With allowImage it also lets the user attach a photo
// (JPEG/PNG up to 5 MB) with an optional caption.
export default function SendForm({ title, description, buttonLabel, send, allowImage = false }) {
  const [phone, setPhone] = useState('');
  const [image, setImage] = useState(null);
  const [caption, setCaption] = useState('');
  const [loading, setLoading] = useState(false);
  const fileInput = useRef(null);

  // Preview URL for the chosen photo, released when it changes or the form closes.
  const [preview, setPreview] = useState('');
  useEffect(() => {
    if (!image) return undefined;
    const url = URL.createObjectURL(image);
    setPreview(url);
    return () => {
      URL.revokeObjectURL(url);
      setPreview('');
    };
  }, [image]);

  const clearImage = () => {
    setImage(null);
    setCaption('');
    if (fileInput.current) fileInput.current.value = '';
  };

  const handleFile = (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    if (!['image/jpeg', 'image/png'].includes(file.type)) {
      showError('Only JPEG or PNG images are supported.', 'Unsupported file');
      e.target.value = '';
      return;
    }
    if (file.size > MAX_IMAGE_BYTES) {
      showError('Image must be 5 MB or smaller.', 'File too large');
      e.target.value = '';
      return;
    }
    setImage(file);
  };

  const reset = () => {
    setPhone('');
    clearImage();
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (loading) return;
    if (!isValidPhone(phone)) {
      showError(PHONE_ERROR, 'Invalid phone number');
      return;
    }
    setLoading(true);
    try {
      const data = await send(phone, { image, caption: caption.trim() });
      if (data.success) {
        showSuccess(
          'Accepted by Meta',
          `${data.message} Check History for delivery status. (ID: ${data.message_id})`,
        );
        reset();
      } else {
        showError(data.error || data.message, 'Not sent');
      }
    } catch (err) {
      showError(err.message, 'Not sent');
    } finally {
      setLoading(false);
    }
  };

  return (
    <Card className="max-w-2xl">
      <h2 className="text-xl font-bold">{title}</h2>
      <p className="mt-1 text-sm text-slate-500">{description}</p>

      <form onSubmit={handleSubmit} noValidate>
        <label htmlFor="phone" className="mb-1.5 mt-5 block text-sm font-semibold">
          Recipient Phone Number
        </label>
        <input
          id="phone"
          type="tel"
          placeholder="9876543210"
          value={phone}
          onChange={(e) => setPhone(e.target.value)}
          disabled={loading}
          autoComplete="off"
          className={inputClass}
        />

        {allowImage && (
          <div className="mt-5">
            <span className="mb-1.5 block text-sm font-semibold">Photo (optional)</span>
            {!image ? (
              <label
                htmlFor="photo"
                className="flex cursor-pointer flex-col items-center justify-center rounded-xl border-2 border-dashed border-slate-300 px-4 py-8 text-center text-sm text-slate-500 transition hover:border-emerald-400 hover:bg-emerald-50"
              >
                <span className="text-3xl" aria-hidden="true">
                  🖼️
                </span>
                <span className="mt-1 font-semibold text-slate-700">Choose a photo</span>
                <span>JPEG or PNG, up to 5 MB</span>
              </label>
            ) : (
              <div className="rounded-xl bg-slate-50 p-3 ring-1 ring-slate-200">
                <img
                  src={preview}
                  alt="Selected preview"
                  className="mx-auto max-h-64 rounded-lg object-contain"
                />
                <div className="mt-2 flex items-center justify-between gap-2 text-sm">
                  <span className="truncate text-slate-600">{image.name}</span>
                  <Button variant="danger" className="!py-1.5" onClick={clearImage} disabled={loading}>
                    Remove
                  </Button>
                </div>
              </div>
            )}
            <input
              ref={fileInput}
              id="photo"
              type="file"
              accept="image/png,image/jpeg"
              onChange={handleFile}
              disabled={loading}
              className="sr-only"
            />

            {image && (
              <>
                <label htmlFor="caption" className="mb-1.5 mt-4 block text-sm font-semibold">
                  Caption (optional)
                </label>
                <textarea
                  id="caption"
                  rows={3}
                  maxLength={MAX_CAPTION}
                  placeholder="Add a caption..."
                  value={caption}
                  onChange={(e) => setCaption(e.target.value)}
                  disabled={loading}
                  className={inputClass}
                />
                <div className="mt-1 text-right text-xs text-slate-500">
                  {caption.length}/{MAX_CAPTION}
                </div>
              </>
            )}
          </div>
        )}

        <div className="mt-6 flex gap-2">
          <Button type="submit" className="flex-1" disabled={loading}>
            {loading ? (
              <>
                <Spinner /> Sending...
              </>
            ) : image ? (
              'Send Photo'
            ) : (
              buttonLabel
            )}
          </Button>
          <Button variant="secondary" onClick={reset} disabled={loading}>
            Clear
          </Button>
        </div>
      </form>
    </Card>
  );
}
