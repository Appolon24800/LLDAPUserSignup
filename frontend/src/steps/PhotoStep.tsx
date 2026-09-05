import { Camera, RefreshCw } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { sniffImage } from "../validation";

export default function PhotoStep({
  photo,
  onChange,
  onError,
  maxMb = 2,
}: {
  photo: File | null;
  onChange: (file: File | null) => void;
  onError: (code: string) => void;
  maxMb?: number;
}) {
  const { t } = useTranslation();
  const [preview, setPreview] = useState<string | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!photo) {
      setPreview(null);
      return;
    }
    const url = URL.createObjectURL(photo);
    setPreview(url);
    return () => URL.revokeObjectURL(url);
  }, [photo]);

  async function accept(file: File | undefined) {
    if (!file) return;
    if (file.size > maxMb * 1024 * 1024) {
      onError("photo_too_large");
      return;
    }
    if (!(await sniffImage(file))) {
      onError("photo_unsupported");
      return;
    }
    onChange(file);
  }

  return (
    <div className="fade-in">
      <label className="field-label" htmlFor="photo-input">
        <Camera aria-hidden />
        {t("fields.photo.label")}
      </label>
      <input
        id="photo-input"
        ref={inputRef}
        className="visually-hidden"
        type="file"
        accept="image/jpeg,image/png,image/gif,image/webp"
        onChange={(e) => void accept(e.target.files?.[0])}
      />
      <div
        className={`photo-drop ${dragOver ? "dragover" : ""}`}
        role="button"
        tabIndex={0}
        aria-labelledby="photo-input"
        onClick={() => inputRef.current?.click()}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") inputRef.current?.click();
        }}
        onDragOver={(e) => {
          e.preventDefault();
          setDragOver(true);
        }}
        onDragLeave={() => setDragOver(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragOver(false);
          void accept(e.dataTransfer.files?.[0]);
        }}
      >
        {preview ? (
          <>
            <img className="photo-preview" src={preview} alt="" />
            <span>{photo?.name}</span>
            <span
              role="button"
              tabIndex={0}
              className="btn ghost"
              onClick={(e) => {
                e.stopPropagation();
                inputRef.current?.click();
              }}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.stopPropagation();
                  inputRef.current?.click();
                }
              }}
            >
              <RefreshCw aria-hidden />
              {t("buttons.changePhoto")}
            </span>
          </>
        ) : (
          <>
            <Camera aria-hidden />
            <span>{t("buttons.addPhoto")}</span>
          </>
        )}
      </div>
      <p className="field-hint">{t("fields.photo.hint")}</p>
    </div>
  );
}
