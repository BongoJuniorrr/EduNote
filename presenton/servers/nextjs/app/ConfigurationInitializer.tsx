'use client';

import { useEffect, useState } from 'react';
import { setCanChangeKeys, setLLMConfig } from '@/store/slices/userConfig';
import { hasValidLLMConfig } from '@/utils/storeHelpers';
import { usePathname, useRouter } from 'next/navigation';
import { useDispatch } from 'react-redux';
import { checkIfSelectedOllamaModelIsPulled } from '@/utils/providerUtils';
import { LLMConfig } from '@/types/llm_config';
import { withBasePath } from '@/utils/basePath';

export function ConfigurationInitializer({ children }: { children: React.ReactNode }) {
  const dispatch = useDispatch();

  const [isLoading, setIsLoading] = useState(true);
  const router = useRouter();
  const route = usePathname();

  // Fetch user config state
  useEffect(() => {
    fetchUserConfigState();
  }, []);

  const setLoadingToFalseAfterNavigatingTo = (pathname: string) => {
    const target = withBasePath(pathname);
    const fallbackTimeout = setTimeout(() => {
      setIsLoading(false);
    }, 5000);

    const interval = setInterval(() => {
      const currentPath = window.location.pathname;
      if (currentPath === target || currentPath.endsWith(pathname)) {
        clearTimeout(fallbackTimeout);
        clearInterval(interval);
        setIsLoading(false);
      }
    }, 200);
  }

  const fetchUserConfigState = async () => {
    try {
      setIsLoading(true);
      const canChangeResponse = await fetch(withBasePath('/api/can-change-keys'));
      if (!canChangeResponse.ok) {
        throw new Error(`can-change-keys returned ${canChangeResponse.status}`);
      }
      const canChangeKeys = (await canChangeResponse.json()).canChange;
      dispatch(setCanChangeKeys(canChangeKeys));

      if (canChangeKeys) {
        const configResponse = await fetch(withBasePath('/api/user-config'));
        if (!configResponse.ok) {
          throw new Error(`user-config returned ${configResponse.status}`);
        }
        const llmConfig = await configResponse.json();
        if (!llmConfig.LLM) {
          llmConfig.LLM = 'openai';
        }
        dispatch(setLLMConfig(llmConfig));
        const isValid = hasValidLLMConfig(llmConfig);
        if (isValid) {
          // Check if the selected Ollama model is pulled
          if (llmConfig.LLM === 'ollama') {
            const isPulled = await checkIfSelectedOllamaModelIsPulled(llmConfig.OLLAMA_MODEL);
            if (!isPulled) {
              router.push('/');
              setLoadingToFalseAfterNavigatingTo('/');
              return;
            }
          }
          if (llmConfig.LLM === 'custom') {
            const isAvailable = await checkIfSelectedCustomModelIsAvailable(llmConfig);
            if (!isAvailable) {
              router.push('/');
              setLoadingToFalseAfterNavigatingTo('/');
              return;
            }
          }
          if (route === '/') {
            router.push('/upload');
            setLoadingToFalseAfterNavigatingTo('/upload');
          } else {
            setIsLoading(false);
          }
        } else if (route !== '/') {
          router.push('/');
          setLoadingToFalseAfterNavigatingTo('/');
        } else {
          setIsLoading(false);
        }
      } else {
        if (route === '/') {
          router.push('/upload');
          setLoadingToFalseAfterNavigatingTo('/upload');
        } else {
          setIsLoading(false);
        }
      }
    } catch (error) {
      console.error('Configuration initialization failed:', error);
      setIsLoading(false);
    }
  }


  const checkIfSelectedCustomModelIsAvailable = async (llmConfig: LLMConfig) => {
    try {
      const response = await fetch(withBasePath('/api/v1/ppt/openai/models/available'), {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          url: llmConfig.CUSTOM_LLM_URL,
          api_key: llmConfig.CUSTOM_LLM_API_KEY,
        }),
      });
      const data = await response.json();
      return data.includes(llmConfig.CUSTOM_MODEL);
    } catch (error) {
      console.error('Error fetching custom models:', error);
      return false;
    }
  }


  if (isLoading) {
    return (
      <div className="min-h-screen bg-gradient-to-br from-[#E9E8F8] via-[#F5F4FF] to-[#E0DFF7] flex items-center justify-center p-4">
        <div className="max-w-md w-full">
          <div className="bg-white/80 backdrop-blur-sm rounded-2xl shadow-xl border border-white/20 p-8 text-center">
            {/* Logo/Branding */}
            <div className="mb-6">
              <img
                src={withBasePath("/Logo.png")}
                alt="EduNote Slides"
                className="h-12 mx-auto mb-4 opacity-90"
              />
              <div className="w-16 h-1 bg-gradient-to-r from-blue-500 to-purple-600 mx-auto rounded-full"></div>
            </div>

            {/* Loading Text */}
            <div className="space-y-2">
              <h3 className="text-lg font-semibold text-gray-800 font-inter">
                Initializing EduNote Slides
              </h3>
              <p className="text-sm text-gray-600 font-inter">
                Loading configuration and checking model availability...
              </p>
            </div>

            {/* Progress Indicator */}
            <div className="mt-6">
              <div className="flex space-x-1 justify-center">
                <div className="w-2 h-2 bg-blue-500 rounded-full animate-pulse"></div>
                <div className="w-2 h-2 bg-purple-500 rounded-full animate-pulse" style={{ animationDelay: '0.2s' }}></div>
                <div className="w-2 h-2 bg-blue-500 rounded-full animate-pulse" style={{ animationDelay: '0.4s' }}></div>
              </div>
            </div>
          </div>
        </div>
      </div>
    );
  }

  return children;
}
