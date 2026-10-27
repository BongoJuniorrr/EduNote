"use client";

import React from "react";
import FontManager from "./components/FontManager";
import Header from "../dashboard/components/Header";

import { useCustomLayout } from "./hooks/useCustomLayout";
import { useFontManagement } from "./hooks/useFontManagement";
import { useFileUpload } from "./hooks/useFileUpload";
import { useSlideProcessing } from "./hooks/useSlideProcessing";
import { useLayoutSaving } from "./hooks/useLayoutSaving";
import { useAPIKeyCheck } from "./hooks/useAPIKeyCheck";
import { useRouter } from "next/navigation";
import { LoadingSpinner } from "./components/LoadingSpinner";
import { FileUploadSection } from "./components/FileUploadSection";
import { SaveLayoutButton } from "./components/SaveLayoutButton";
import { SaveLayoutModal } from "./components/SaveLayoutModal";
import EachSlide from "./components/EachSlide/NewEachSlide";
import { APIKeyWarning } from "./components/APIKeyWarning";
import { trackEvent, MixpanelEvent } from "@/utils/mixpanel";
import { getCriticLabel, getCriticTone } from "./utils/templateCritic";

const CustomTemplatePage = () => {
  const router = useRouter();


  // Custom hooks for different concerns
  const { hasRequiredKey, isRequiredKeyLoading } = useAPIKeyCheck();
  const { selectedFile, handleFileSelect, removeFile } = useFileUpload();
  const { slides, setSlides, completedSlides } = useCustomLayout();
  const { fontsData, UploadedFonts, uploadFont, removeFont, getAllUnsupportedFonts, setFontsData } = useFontManagement();
  const { isProcessingPptx, processFile, retrySlide, processSlideToHtml } = useSlideProcessing(
    selectedFile,
    slides,
    setSlides,
    setFontsData
  );
  const { isSavingLayout, isModalOpen, openSaveModal, closeSaveModal, saveLayout } = useLayoutSaving(
    slides,
    UploadedFonts,
    fontsData,

    setSlides
  );

  const handleSaveTemplate = async (layoutName: string, description: string): Promise<string | null> => {
    trackEvent(MixpanelEvent.CustomTemplate_Save_Templates_API_Call);
    const id = await saveLayout(layoutName, description);
    if (id) {
      router.push(`/template-preview/custom-${id}`);
    }
    return id;
  };

  const handleProcessSlideToHtml = (slide: any) => {
    processSlideToHtml(slide, 0)
  }

  const criticOverview = React.useMemo(() => {
    const scoredSlides = slides.filter((slide) => slide.critic);
    if (!scoredSlides.length) {
      return null;
    }

    const score = Math.round(
      scoredSlides.reduce((sum, slide) => sum + (slide.critic?.score || 0), 0) /
        scoredSlides.length
    );
    const riskCounts = new Map<string, number>();
    scoredSlides.forEach((slide) => {
      slide.critic?.risks.forEach((risk) => {
        const normalized = risk.trim();
        if (!normalized) return;
        riskCounts.set(normalized, (riskCounts.get(normalized) || 0) + 1);
      });
    });
    const topRisks = Array.from(riskCounts.entries())
      .sort((a, b) => b[1] - a[1])
      .slice(0, 3)
      .map(([risk]) => risk);

    return {
      score,
      label: getCriticLabel(score),
      tone: getCriticTone(score),
      readyCount: scoredSlides.filter((slide) => (slide.critic?.score || 0) >= 70).length,
      reviewedCount: scoredSlides.length,
      totalCount: slides.length,
      topRisks,
      model: scoredSlides.find((slide) => slide.critic?.model)?.critic?.model,
      visualProvider:
        scoredSlides.find((slide) => slide.critic?.visual_provider)?.critic
          ?.visual_provider || undefined,
      guidance:
        score >= 85
          ? "Good enough to save now. Minor polishing only."
          : score >= 70
          ? "Usable, but review the weak slides before saving."
          : score >= 55
          ? "Borderline quality. Save only if you plan to refine the converted slides."
          : "Low quality. Review carefully before you rely on this template pack.",
    };
  }, [slides]);

  // Handle slide updates
  const handleSlideUpdate = (index: number, updatedSlideData: any) => {
    setSlides((prevSlides) =>
      prevSlides.map((s, i) =>
        i === index
          ? {
            ...s,
            ...updatedSlideData,
            modified: true,
          }
          : s
      )
    );
  };

  // Loading state
  if (isRequiredKeyLoading) {
    return <LoadingSpinner message="Checking API Key..." />;
  }

  // Anthropic key warning
  if (!hasRequiredKey) {
    return <APIKeyWarning />;


  }
  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-50 to-slate-100">
      <Header />
      <div className="max-w-[1440px] aspect-video mx-auto px-6">
        {/* Header */}
        <div className="text-center space-y-2 my-6">
          <h1 className="text-4xl font-bold text-gray-900 flex items-center justify-center gap-3">
            <span>Custom Template Processor</span>
            <span className="inline-flex items-center rounded-full border border-orange-300 bg-orange-50 px-3 py-1 text-xs font-semibold uppercase tracking-[0.18em] text-orange-700 shadow-sm">
              Beta
            </span>
          </h1>
          <p className="text-lg text-gray-600 max-w-2xl mx-auto">
            Upload your PDF or PPTX file to extract slides and convert them to
            a template which you can use to generate AI presentations.
          </p>
          <div className="max-w-2xl mx-auto mt-2">
            <div className="inline-block rounded border border-orange-200 bg-orange-50 px-3 py-2 text-sm text-orange-700">
              AI template generation can take around 5 minutes per slide.
            </div>
          </div>
        </div>


        {/* File Upload Section */}
        <FileUploadSection
          selectedFile={selectedFile}
          handleFileSelect={handleFileSelect}
          removeFile={removeFile}
          processFile={processFile}
          isProcessingPptx={isProcessingPptx}
          slides={slides}
          completedSlides={completedSlides}
        />

        {/* Global Font Management */}
        {fontsData && (
          <FontManager
            fontsData={fontsData}
            UploadedFonts={UploadedFonts}
            uploadFont={uploadFont}
            removeFont={removeFont}
            getAllUnsupportedFonts={getAllUnsupportedFonts}
            processSlideToHtml={() => handleProcessSlideToHtml(slides[0])}
          />
        )}

        {criticOverview && (
          <div className="mt-8 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
            <div className="flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
              <div>
                <div className="flex flex-wrap items-center gap-3">
                  <span className="text-sm font-semibold uppercase tracking-[0.16em] text-slate-500">
                    Template Critic
                  </span>
                  <span
                    className={`inline-flex rounded-full px-3 py-1 text-xs font-semibold ${
                      criticOverview.tone === "good"
                        ? "bg-emerald-50 text-emerald-700"
                        : criticOverview.tone === "warn"
                        ? "bg-amber-50 text-amber-700"
                        : "bg-rose-50 text-rose-700"
                    }`}
                  >
                    {criticOverview.label}
                  </span>
                </div>
                <div className="mt-3 flex items-end gap-3">
                  <span className="text-4xl font-bold text-slate-900">
                    {criticOverview.score}
                  </span>
                  <span className="pb-1 text-base text-slate-500">/ 100 overall</span>
                </div>
                <p className="mt-2 max-w-2xl text-sm text-slate-600">
                  {criticOverview.guidance}
                </p>
              </div>
              <div className="grid gap-3 text-sm text-slate-600 md:min-w-[320px]">
                <div className="rounded-xl bg-slate-50 px-4 py-3">
                  <span className="font-semibold text-slate-900">
                    {criticOverview.readyCount}/{criticOverview.totalCount}
                  </span>{" "}
                  slides are currently strong enough to reuse with light edits.
                </div>
                <div className="rounded-xl bg-slate-50 px-4 py-3">
                  Reviewed slides:{" "}
                  <span className="font-semibold text-slate-900">
                    {criticOverview.reviewedCount}
                  </span>
                  {criticOverview.model ? (
                    <>
                      {" "}• Critiqued with{" "}
                      <span className="font-semibold text-slate-900">
                        {criticOverview.model}
                      </span>
                    </>
                  ) : null}
                  {criticOverview.visualProvider ? (
                    <>
                      {" "}• Visual pipeline{" "}
                      <span className="font-semibold text-slate-900">
                        {criticOverview.visualProvider}
                      </span>
                    </>
                  ) : null}
                </div>
              </div>
            </div>
            {criticOverview.topRisks.length > 0 && (
              <div className="mt-4">
                <p className="text-xs font-semibold uppercase tracking-[0.16em] text-slate-500">
                  Most Frequent Risks
                </p>
                <div className="mt-2 flex flex-wrap gap-2">
                  {criticOverview.topRisks.map((risk) => (
                    <span
                      key={risk}
                      className="inline-flex rounded-full bg-slate-100 px-3 py-1 text-xs text-slate-700"
                    >
                      {risk}
                    </span>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}

        {/* Slides Section */}
        {slides.length > 0 && (
          <div className="space-y-6 mt-10">
            {slides.map((slide, index) => (
              <EachSlide
                key={index}
                slide={slide}
                index={index}
                isProcessing={slides.some((s) => s.processing)}
                retrySlide={retrySlide}
                setSlides={setSlides}
                onSlideUpdate={(updatedSlideData) =>
                  handleSlideUpdate(index, updatedSlideData)
                }
              />
            ))}
          </div>
        )}

        {/* Floating Save Template Button */}
        {slides.length > 0 && slides.some((s) => s.processed) && (
          <SaveLayoutButton
            onSave={openSaveModal}
            isSaving={isSavingLayout}
            isProcessing={slides.some((s) => s.processing)}
          />
        )}

        {/* Save Template Modal */}
        <SaveLayoutModal
          isOpen={isModalOpen}
          onClose={closeSaveModal}
          onSave={handleSaveTemplate}
          isSaving={isSavingLayout}
        />
      </div>
    </div>
  );
};

export default CustomTemplatePage;
