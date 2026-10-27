'use client'

import React from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useDrawingCanvas } from "../../hooks/useDrawingCanvas";  

import { EachSlideProps } from "../../types";
import { SlideContentDisplay } from "./SlideContentDisplay";
import { useHtmlEdit } from "../../hooks/useHtmlEdit";
import { SlideActions } from "./SlideActions";
import { HtmlEditor } from "./HtmlEditor";
import { EditControls } from "./EditControls";
import { useSlideEdit } from "../../hooks/useSlideEdit";
import { getCriticLabel, getCriticTone } from "../../utils/templateCritic";

const EachSlide: React.FC<EachSlideProps> = ({
  slide,
  index,
  retrySlide,
  setSlides,
  onSlideUpdate,
  isProcessing,
}) => {
  // Custom hooks
  const {
    canvasRef,
    slideDisplayRef,
    strokeWidth,
    strokeColor,
    eraserMode,
    isDrawing,
    canvasDimensions,
    setCanvasDimensions,
    didYourDraw,
    handleMouseDown,
    handleMouseMove,
    handleMouseUp,
    handleTouchStart,
    handleTouchMove,
    handleTouchEnd,
    handleClearCanvas,
    handleEraserModeChange,
    handleStrokeColorChange,
    handleStrokeWidthChange,
  } = useDrawingCanvas();

  const {
    isEditMode,
    isUpdating,
    prompt,
    slideContentRef,
    setPrompt,
    handleSave,
    handleEditClick,
    handleCancelEdit,
  } = useSlideEdit(slide, index, onSlideUpdate, setSlides);

  const {
    isHtmlEditMode,
    handleHtmlEditClick,
    handleHtmlEditCancel,
    handleHtmlSave,
  } = useHtmlEdit(slide, index, onSlideUpdate, setSlides);

  // Set canvas dimensions when entering edit mode
  React.useEffect(() => {
    if (isEditMode && slideContentRef.current && slide.html) {
      const rect = slideContentRef.current.getBoundingClientRect();
      setCanvasDimensions({
        width: Math.max(rect.width, 800),
        height: Math.max(rect.height, 600),
      });
    }
  }, [isEditMode, slide.html, slideContentRef, setCanvasDimensions]);

  // Handle save with drawing data
  const handleSaveWithDrawing = () => {
    handleSave(slideDisplayRef!, didYourDraw);
  };

  // Handle delete slide
  const handleDeleteSlide = () => {
    setSlides((prevSlides) => prevSlides.filter((_, i) => i !== index));
  };

  // Handle retry slide
  const handleRetrySlide = () => {
    retrySlide(index);
  };

	  return (
    <Card
      key={slide.slide_number}
      className="border-2 font-instrument_sans w-full relative"
    >
      <CardHeader className="max-w-[1280px] mx-auto px-0 py-6">
        <CardTitle className="text-xl">
          <SlideActions
            slide={slide}
            index={index}
            isProcessing={isProcessing}
            isEditMode={isEditMode}
            isHtmlEditMode={isHtmlEditMode}
            onEditClick={handleEditClick}
            onHtmlEditClick={handleHtmlEditClick}
            onRetry={handleRetrySlide}
            onDelete={handleDeleteSlide}
          />
        </CardTitle>
      </CardHeader>

	      <CardContent className="space-y-4">
	        {slide.processed && (
	          <div className="rounded-xl border border-slate-200 bg-slate-50 p-4">
	            <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
	              <div>
	                <div className="flex flex-wrap items-center gap-3">
	                  <span className="text-xs font-semibold uppercase tracking-[0.16em] text-slate-500">
	                    Slide Critic
	                  </span>
	                  {slide.critic ? (
	                    <span
	                      className={`inline-flex rounded-full px-3 py-1 text-xs font-semibold ${
	                        getCriticTone(slide.critic.score) === "good"
	                          ? "bg-emerald-50 text-emerald-700"
	                          : getCriticTone(slide.critic.score) === "warn"
	                          ? "bg-amber-50 text-amber-700"
	                          : "bg-rose-50 text-rose-700"
	                      }`}
	                    >
	                      {getCriticLabel(slide.critic.score)}
	                    </span>
	                  ) : null}
	                </div>
	                {slide.criticLoading ? (
	                  <p className="mt-2 text-sm text-slate-600">
	                    Scoring this template conversion...
	                  </p>
	                ) : slide.critic ? (
	                  <>
	                    <div className="mt-2 flex items-end gap-3">
	                      <span className="text-3xl font-bold text-slate-900">
	                        {slide.critic.score}
	                      </span>
	                      <span className="pb-1 text-sm text-slate-500">/ 100</span>
	                    </div>
	                    <p className="mt-2 text-sm text-slate-600">
	                      {slide.critic.summary}
	                    </p>
	                    <p className="mt-2 text-xs text-slate-500">
	                      {slide.critic.save_guidance}
	                    </p>
	                  </>
	                ) : slide.criticError ? (
	                  <p className="mt-2 text-sm text-rose-600">
	                    Critic unavailable: {slide.criticError}
	                  </p>
	                ) : (
	                  <p className="mt-2 text-sm text-slate-500">
	                    Score will appear after the HTML conversion finishes.
	                  </p>
	                )}
	              </div>
	              {slide.critic && (
	                <div className="grid min-w-[280px] gap-2 text-xs text-slate-600 sm:grid-cols-2">
	                  {Object.entries(slide.critic.breakdown).map(([key, value]) => (
	                    <div key={key} className="rounded-lg bg-white px-3 py-2 shadow-sm">
	                      <div className="uppercase tracking-[0.12em] text-[10px] text-slate-400">
	                        {key.replace(/_/g, " ")}
	                      </div>
	                      <div className="mt-1 font-semibold text-slate-900">
	                        {value}/100
	                      </div>
	                    </div>
	                  ))}
	                </div>
	              )}
	            </div>
	            {slide.critic && (
	              <div className="mt-4 grid gap-4 md:grid-cols-3">
	                <div>
	                  <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-500">
	                    Strengths
	                  </p>
	                  <ul className="mt-2 space-y-1 text-sm text-slate-600">
	                    {slide.critic.strengths.slice(0, 3).map((item) => (
	                      <li key={item}>• {item}</li>
	                    ))}
	                  </ul>
	                </div>
	                <div>
	                  <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-500">
	                    Risks
	                  </p>
	                  <ul className="mt-2 space-y-1 text-sm text-slate-600">
	                    {slide.critic.risks.slice(0, 3).map((item) => (
	                      <li key={item}>• {item}</li>
	                    ))}
	                  </ul>
	                </div>
	                <div>
	                  <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-500">
	                    Fix Next
	                  </p>
	                  <ul className="mt-2 space-y-1 text-sm text-slate-600">
	                    {slide.critic.suggested_fixes.slice(0, 3).map((item) => (
	                      <li key={item}>• {item}</li>
	                    ))}
	                  </ul>
	                </div>
	              </div>
	            )}
	          </div>
	        )}
	        {/* HTML Editor */}
	        <HtmlEditor
          slide={slide}
          isHtmlEditMode={isHtmlEditMode}
          onSave={handleHtmlSave}
          onCancel={handleHtmlEditCancel}
        />

        {/* Edit Controls */}
        <EditControls
          isEditMode={isEditMode}
          prompt={prompt}
          isUpdating={isUpdating}
          strokeWidth={strokeWidth}
          strokeColor={strokeColor}
          eraserMode={eraserMode}
          onPromptChange={setPrompt}
          onSave={handleSaveWithDrawing}
          onCancel={handleCancelEdit}
          onStrokeWidthChange={handleStrokeWidthChange}
          onStrokeColorChange={handleStrokeColorChange}
          onEraserModeChange={handleEraserModeChange}
          onClearCanvas={handleClearCanvas}
        />
        {/* Slide Content Display */}
        <SlideContentDisplay
          slide={slide}
          isEditMode={isEditMode}
          isHtmlEditMode={isHtmlEditMode}
          slideContentRef={slideContentRef}
          slideDisplayRef={slideDisplayRef}
          canvasRef={canvasRef}
          canvasDimensions={canvasDimensions}
          strokeWidth={strokeWidth}
          strokeColor={strokeColor}
          eraserMode={eraserMode}
          isDrawing={isDrawing}
          didYourDraw={didYourDraw}
          onMouseDown={handleMouseDown}
          onMouseMove={handleMouseMove}
          onMouseUp={handleMouseUp}
          onTouchStart={handleTouchStart}
          onTouchMove={handleTouchMove}
          retrySlide={handleRetrySlide}
          onTouchEnd={handleTouchEnd}
        />
      </CardContent>
    </Card>
  );
};

export default EachSlide; 
