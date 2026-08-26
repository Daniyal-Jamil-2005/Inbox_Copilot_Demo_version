/**
 * Centralized API Configuration — Portfolio Demo
 * 
 * Single source of truth for backend API connection.
 * Environment Variables:
 * - REACT_APP_API_URL: Base URL for backend API (defaults to localhost:8000)
 */

const getBaseURL = () => {
  if (typeof window !== 'undefined') {
    const customUrl = localStorage.getItem('REACT_APP_API_URL') || localStorage.getItem('VITE_API_URL');
    if (customUrl && customUrl.trim()) {
      return customUrl.trim().replace(/\/+$/, '');
    }
  }
  let url = process.env.REACT_APP_API_URL || process.env.VITE_API_URL;
  if (url && url.trim()) {
    return url.trim().replace(/\/+$/, '');
  }
  return 'http://localhost:8000';
};

const API_CONFIG = {
  // Base URL for all API requests
  baseURL: getBaseURL(),
  
  // API endpoint paths
  endpoints: {
    // Core scanning endpoints
    processFiles: '/process-files',
    sampleData: '/sample-data',
    health: '/health',
    
    // Email scanning endpoints
    scanGmail: '/scan-gmail',
    scanOutlook: '/scan-outlook',
    emailCredentials: '/email-credentials',
    emailProviders: '/email-providers',
    setupInstructions: '/email-setup-instructions',
    
    // Analytics endpoints
    analytics: '/process-with-analytics',
    history: '/analytics/history',
    
    // Demo session management endpoints
    profile: '/profile',
    bookmarks: '/bookmarks',
    checklists: '/checklists',
    resetDemo: '/demo/reset',
  },
  
  // Request timeout in milliseconds (30 seconds)
  timeout: 30000
};

export default API_CONFIG;
