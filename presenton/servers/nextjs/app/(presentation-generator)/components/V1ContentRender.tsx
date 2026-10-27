"use client";

import React, { useMemo, useRef } from "react";
import EditableLayoutWrapper from "../components/EditableLayoutWrapper";
import SlideErrorBoundary from "../components/SlideErrorBoundary";
import TiptapTextReplacer from "../components/TiptapTextReplacer";
import { validate as uuidValidate } from 'uuid';
import { getLayoutByLayoutId } from "@/app/presentation-templates";
import { useCustomTemplateDetails } from "@/app/hooks/useCustomTemplates";
import { updateSlideContent } from "@/store/slices/presentationGeneration";
import { useDispatch } from "react-redux";
import { Loader2 } from "lucide-react";
import { withBasePath } from "@/utils/basePath";
import { normalizeLatexLikeText } from "@/utils/latex";




export const V1ContentRender = ({ slide, isEditMode, theme }: { slide: any, isEditMode: boolean, theme?: any, enableEditMode?: boolean }) => {
    const dispatch = useDispatch();
    const containerRef = useRef<HTMLDivElement | null>(null);

    const isTextLikeContent = (value: string): boolean => {
        if (!value) return false;
        if (/^(?:https?:|data:|blob:)/i.test(value)) return false;
        if (/^\/?(?:app_data|static)\//.test(value)) return false;
        if (value.includes("url(") || /\b(?:src|href)\s*=/.test(value)) return false;
        return true;
    };

    const normalizeSlideContentAssets = (value: any): any => {
        if (typeof value === "string") {
            const normalizedValue =
                value.startsWith("app_data/") || value.startsWith("static/")
                    ? `/${value}`
                    : value;

            if (
                normalizedValue.startsWith("/app_data/") ||
                normalizedValue.startsWith("/static/")
            ) {
                return withBasePath(normalizedValue);
            }

            const normalizedCssUrls = normalizedValue.replace(
                /url\((['"]?)(\/?(?:app_data|static)\/[^)'"]+)\1\)/g,
                (_, quote, assetPath) => {
                    const normalizedAssetPath = assetPath.startsWith("/")
                        ? assetPath
                        : `/${assetPath}`;
                    return `url(${quote}${withBasePath(normalizedAssetPath)}${quote})`;
                }
            );

            const normalizedWithAttrs = normalizedCssUrls.replace(
                /\b(src|href|poster)=("|')?(\/?(?:app_data|static)\/[^"' >]+)\2?/g,
                (_, attribute, quote = '"', assetPath) => {
                    const normalizedAssetPath = assetPath.startsWith("/")
                        ? assetPath
                        : `/${assetPath}`;
                    return `${attribute}=${quote}${withBasePath(normalizedAssetPath)}${quote}`;
                }
            );

            if (isTextLikeContent(normalizedWithAttrs)) {
                return normalizeLatexLikeText(normalizedWithAttrs);
            }

            return normalizedWithAttrs;
        }
        if (Array.isArray(value)) {
            return value.map(normalizeSlideContentAssets);
        }
        if (value && typeof value === "object") {
            return Object.fromEntries(
                Object.entries(value).map(([key, nestedValue]) => [
                    key,
                    normalizeSlideContentAssets(nestedValue),
                ])
            );
        }
        return value;
    };

    const normalizedSlideContent = useMemo(
        () => normalizeSlideContentAssets(slide.content),
        [slide.content]
    );


    const customTemplateId = slide.layout_group.startsWith("custom-") ? slide.layout_group.split("custom-")[1] : slide.layout_group;
    const isCustomTemplate = uuidValidate(customTemplateId) || slide.layout_group.startsWith("custom-");

    // Always call the hook (React hooks rule), but with empty id when not a custom template
    const { template: customTemplate, loading: customLoading, fonts } = useCustomTemplateDetails({
        id: isCustomTemplate ? customTemplateId : "",
        name: isCustomTemplate ? slide.layout_group : "",
        description: ""
    });
    if (fonts && typeof fonts === 'object') {
        // useFontLoader(fonts as unknown as Record<string, string>);
    }

    // Memoize layout resolution to prevent unnecessary recalculations
    const Layout = useMemo(() => {
        if (isCustomTemplate) {
            if (customTemplate) {
                const layoutId = slide.layout.startsWith("custom-") ? slide.layout.split(":")[1] : slide.layout;


                const compiledLayout = customTemplate.layouts.find(
                    (layout) => layout.layoutId === layoutId
                );


                return compiledLayout?.component ?? null;
            }
            return null;
        } else {
            const template = getLayoutByLayoutId(slide.layout);
            return template?.component ?? null;
        }
    }, [isCustomTemplate, customTemplate, slide.layout]);

    // Show loading state for custom templates
    if (isCustomTemplate && customLoading) {
        return (
            <div className="flex flex-col items-center justify-center aspect-video h-full bg-gray-100 rounded-lg">
                <Loader2 className="w-4 h-4 animate-spin" />
            </div>
        );
    }


    if (!Layout) {
        if (Object.keys(slide.content).length === 0) {
            return (
                <div className="flex flex-col items-center cursor-pointer justify-center aspect-video h-full bg-gray-100 rounded-lg">
                    <p className="text-gray-600 text-center text-base">Blank Slide</p>
                    <p className="text-gray-600 text-center text-sm">This slide is empty. Please add content to it using the edit button.</p>
                </div>
            )
        }
        return (
            <div className="flex flex-col items-center justify-center aspect-video h-full bg-gray-100 rounded-lg">
                <p className="text-gray-600 text-center text-base">
                    Layout &quot;{slide.layout}&quot; not found in &quot;
                    {slide.layout_group}&quot; Template
                </p>
            </div>
        );
    }
    const LayoutComp = Layout as React.ComponentType<{ data: any }>;

    if (isEditMode) {
        return (
            <SlideErrorBoundary label={`Slide ${slide.index + 1}`}>
                <div ref={containerRef} className={`w-full h-full `}>

                    <EditableLayoutWrapper
                        slideIndex={slide.index}
                        slideData={slide.content}
                        properties={slide.properties}
                    >
                        <TiptapTextReplacer
                            key={slide.id}
                            slideData={slide.content}
                            slideIndex={slide.index}
                            onContentChange={(
                                content: string,
                                dataPath: string,
                                slideIndex?: number
                            ) => {
                                if (dataPath && slideIndex !== undefined) {
                                    dispatch(
                                        updateSlideContent({
                                            slideIndex: slideIndex,
                                            dataPath: dataPath,
                                            content: content,
                                        })
                                    );
                                }
                            }}
                        >
                            <LayoutComp data={{
                                ...normalizedSlideContent,
                                _logo_url__: theme ? theme.logo_url : null,
                                __companyName__: (theme && theme.company_name) ? theme.company_name : null,
                            }} />
                        </TiptapTextReplacer>
                    </EditableLayoutWrapper>



                </div>
            </SlideErrorBoundary>

        );
    }
    return (
        <LayoutComp data={{
            ...normalizedSlideContent,
            _logo_url__: theme ? theme.logo_url : null,
            __companyName__: (theme && theme.company_name) ? theme.company_name : null,
        }} />
    )
};
