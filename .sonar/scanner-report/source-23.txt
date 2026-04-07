"use client";

import { useCallback, useRef } from "react";
import { Upload, FilePlus } from "lucide-react";

interface Props {
  onFiles: (files: File[]) => void;
  disabled?: boolean;
  isDragging: boolean;
  onDragChange: (dragging: boolean) => void;
}

export function FileDropzone({ onFiles, disabled = false, isDragging, onDragChange }: Props) {
  const inputRef = useRef<HTMLInputElement>(null);

  const accept = useCallback(
    (incoming: FileList | null) => {
      if (!incoming) return;
      const valid = Array.from(incoming).filter((f) =>
        f.name.toLowerCase().endsWith(".pdf")
      );
      if (valid.length) onFiles(valid);
    },
    [onFiles]
  );

  const onDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      onDragChange(false);
      if (!disabled) accept(e.dataTransfer.files);
    },
    [disabled, accept, onDragChange]
  );

  return (
    <div
      onDrop={onDrop}
      onDragOver={(e) => { e.preventDefault(); if (!disabled) onDragChange(true); }}
      onDragLeave={() => onDragChange(false)}
      onDragEnd={() => onDragChange(false)}
      onClick={() => !disabled && inputRef.current?.click()}
      className={`
        relative border-2 border-dashed rounded-2xl p-12 text-center cursor-pointer
        transition-all duration-200 select-none
        ${disabled
          ? "opacity-40 cursor-not-allowed border-slate-700 bg-slate-900/30"
          : isDragging
          ? "border-aura-accent bg-aura-accent/5 scale-[1.01]"
          : "border-slate-600 hover:border-aura-primary hover:bg-aura-primary/5"
        }
      `}
    >
      {/* Animated corner accents when dragging */}
      {isDragging && (
        <>
          <span className="absolute top-2 left-2 w-4 h-4 border-t-2 border-l-2 border-aura-accent rounded-tl" />
          <span className="absolute top-2 right-2 w-4 h-4 border-t-2 border-r-2 border-aura-accent rounded-tr" />
          <span className="absolute bottom-2 left-2 w-4 h-4 border-b-2 border-l-2 border-aura-accent rounded-bl" />
          <span className="absolute bottom-2 right-2 w-4 h-4 border-b-2 border-r-2 border-aura-accent rounded-br" />
        </>
      )}

      <div className={`flex flex-col items-center gap-3 transition-transform duration-150 ${isDragging ? "scale-105" : ""}`}>
        {isDragging ? (
          <FilePlus size={44} className="text-aura-accent" />
        ) : (
          <Upload size={44} className="text-slate-500" />
        )}
        <div>
          <p className={`text-lg font-semibold ${isDragging ? "text-aura-accent" : "text-white"}`}>
            {isDragging ? "Release to add files" : "Drop PDFs here"}
          </p>
          <p className="text-slate-500 text-sm mt-1">
            or <span className="text-aura-primary underline underline-offset-2">browse your computer</span>
          </p>
        </div>
        <p className="text-xs text-slate-600 mt-1">PDF files only · No size limit</p>
      </div>

      <input
        ref={inputRef}
        type="file"
        accept=".pdf"
        multiple
        className="hidden"
        disabled={disabled}
        onChange={(e) => accept(e.target.files)}
        // Reset so the same file can be re-added after removal
        onClick={(e) => { (e.target as HTMLInputElement).value = ""; }}
      />
    </div>
  );
}
