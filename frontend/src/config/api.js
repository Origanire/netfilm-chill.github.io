// Configuration centralisée de l'API
const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:5000'

export const API_ENDPOINTS = {
  AKINATOR: `${API_BASE_URL}/akinator`,
  BLINDTEST: `${API_BASE_URL}/blindtest`,
  MOVIEGRID: `${API_BASE_URL}/moviegrid`,
}

export default API_BASE_URL
