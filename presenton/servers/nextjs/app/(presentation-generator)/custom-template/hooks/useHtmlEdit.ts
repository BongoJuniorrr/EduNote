import { useState } from "react";
import { ProcessedSlide } from "../types";
import { requestTemplateCritic } from "../utils/templateCritic";

export const useHtmlEdit = (
  slide: ProcessedSlide,
  index: number,
  onSlideUpdate?: (updatedSlideData: any) => void,
  setSlides?: React.Dispatch<React.SetStateAction<ProcessedSlide[]>>
) => {
  const [isHtmlEditMode, setIsHtmlEditMode] = useState(false);

  const applySlideUpdate = (updatedSlideData: Partial<ProcessedSlide>) => {
    if (onSlideUpdate) {
      onSlideUpdate(updatedSlideData);
      return;
    }
    if (setSlides) {
      setSlides((prevSlides) =>
        prevSlides.map((s, i) => (i === index ? { ...s, ...updatedSlideData } : s))
      );
    }
  };

  const handleHtmlEditClick = () => {
    setIsHtmlEditMode(true);
  };

  const handleHtmlEditCancel = () => {
    setIsHtmlEditMode(false);
  };

  const handleHtmlSave = async (html: string) => {
    const updatedSlideData: Partial<ProcessedSlide> = {
      slide_number: slide.slide_number,
      html: html,
      processed: true,
      processing: false,
      error: undefined,
      modified: true,
      criticLoading: true,
      criticError: undefined,
    };

    applySlideUpdate(updatedSlideData);

    try {
      const critic = await requestTemplateCritic({
        slide_number: slide.slide_number,
        screenshot_url: slide.screenshot_url,
        html,
      });
      applySlideUpdate({
        critic,
        criticLoading: false,
        criticError: undefined,
      });
    } catch (error) {
      applySlideUpdate({
        criticLoading: false,
        criticError:
          error instanceof Error ? error.message : "Failed to score this slide",
      });
    }

    setIsHtmlEditMode(false);
  };

  return {
    isHtmlEditMode,
    handleHtmlEditClick,
    handleHtmlEditCancel,
    handleHtmlSave,
  };
}; 
