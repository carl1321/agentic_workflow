export interface ModelInfo {
  name: string;
  model: string;
  base_url: string;
  api_key?: string;
  completion_path?: string;
  max_retries?: number;
  verify_ssl?: boolean;
  supports_thinking?: boolean;
  azure_endpoint?: string;
  api_version?: string;
  deployment_name?: string;
}

export interface ModelConfig {
  [key: string]: ModelInfo[];
}

export interface RagConfig {
  provider: string;
}

export interface AIResearchAgentConfig {
  rag: RagConfig;
  models: ModelConfig;
}
