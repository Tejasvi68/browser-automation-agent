import { useRef, useState } from "react";
import api from "../api/client";

export function useVoiceInput({ onTranscriptChange }) {
  const [isRecording, setIsRecording] = useState(false);
  const [isPolishing, setIsPolishing] = useState(false);
  const [voiceError, setVoiceError] = useState("");

  const recognitionRef = useRef(null);
  const mediaRecorderRef = useRef(null);
  const chunksRef = useRef([]);

  const startRecording = async () => {
    setVoiceError("");
    chunksRef.current = [];

    // 1. Start live browser speech preview if supported
    const SpeechRecognition =
      window.SpeechRecognition || window.webkitSpeechRecognition;
    if (SpeechRecognition) {
      const recognition = new SpeechRecognition();
      recognition.continuous = true;
      recognition.interimResults = true;
      recognition.lang = "en-IN";

      recognition.onresult = (event) => {
        let liveText = "";
        for (let i = 0; i < event.results.length; i++) {
          liveText += event.results[i][0].transcript;
        }
        if (liveText.trim()) {
          onTranscriptChange(liveText.trim());
        }
      };

      recognition.onerror = () => {
        // Fallback silently to MediaRecorder + Whisper
      };

      recognitionRef.current = recognition;
      recognition.start();
    }

    // 2. Record audio blob for Whisper accuracy pass
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const recorder = new MediaRecorder(stream);
      recorder.ondataavailable = (e) => {
        if (e.data.size > 0) chunksRef.current.push(e.data);
      };
      recorder.onstop = async () => {
        stream.getTracks().forEach((t) => t.stop());
        if (chunksRef.current.length === 0) return;

        const blob = new Blob(chunksRef.current, { type: "audio/webm" });
        const formData = new FormData();
        formData.append("audio", blob, "voice_prompt.webm");

        setIsPolishing(true);
        try {
          const res = await api.post("/transcribe", formData, {
            headers: { "Content-Type": "multipart/form-data" },
          });
          if (res.data?.text) {
            onTranscriptChange(res.data.text);
          }
        } catch {
          // Keep live Web Speech API text if Groq key is unavailable
        } finally {
          setIsPolishing(false);
        }
      };

      mediaRecorderRef.current = recorder;
      recorder.start();
      setIsRecording(true);
    } catch {
      setVoiceError("Microphone permission denied or unavailable.");
      if (recognitionRef.current) recognitionRef.current.stop();
    }
  };

  const stopRecording = () => {
    if (recognitionRef.current) {
      try {
        recognitionRef.current.stop();
      } catch {}
    }
    if (
      mediaRecorderRef.current &&
      mediaRecorderRef.current.state !== "inactive"
    ) {
      mediaRecorderRef.current.stop();
    }
    setIsRecording(false);
  };

  const toggleRecording = () => {
    if (isRecording) {
      stopRecording();
    } else {
      startRecording();
    }
  };

  return { isRecording, isPolishing, voiceError, toggleRecording };
}