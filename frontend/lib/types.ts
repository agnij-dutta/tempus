export type PreviewItem = {
  preview_id: string;
  status: string;
  preview_url: string;
  expires_at: string;
  created_at: string;
  service_status?: string;
  target_group_health?: string;
};

export type PreviewStatusDetail = {
  preview_id: string;
  status: string;
  preview_url: string;
  expires_at: string;
  created_at: string;
  service_status?: string;
  desired_count?: number;
  running_count?: number;
  pending_count?: number;
  target_group_health?: string;
  target_health_descriptions?: any[];
};

export type PreviewListResponse = {
  items: PreviewItem[];
  total: number;
};

export type CreatePreviewResponse = {
  preview_id: string;
  preview_url: string;
  expires_at: string;
};

