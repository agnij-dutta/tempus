import axios from "axios";
import {
  CreatePreviewResponse,
  PreviewListResponse,
  PreviewStatusDetail,
} from "./types";

const api = axios.create({
  baseURL: process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000",
  timeout: 15000,
});

export async function listPreviews() {
  const res = await api.get<PreviewListResponse>("/preview");
  return res.data;
}

export async function getPreview(previewId: string) {
  const res = await api.get<PreviewStatusDetail>(`/preview/${previewId}`);
  return res.data;
}

export async function createPreview(ttl_hours: number) {
  const res = await api.post<CreatePreviewResponse>("/preview/create", {
    ttl_hours,
  });
  return res.data;
}

export async function deletePreview(previewId: string) {
  await api.delete(`/preview/${previewId}`);
}

export async function extendPreview(previewId: string, additional_hours: number) {
  const res = await api.post(`/preview/${previewId}/extend`, {
    additional_hours,
  });
  return res.data;
}

export async function testPreview(previewId: string) {
  const res = await api.get(`/preview/${previewId}/test`);
  return res.data;
}

