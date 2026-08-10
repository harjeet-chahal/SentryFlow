import React, { createContext, useState, useContext, useEffect } from 'react';
import axios from 'axios';
import jwtDecode from 'jwt-decode';

// Create context
const AuthContext = createContext();

// API URL
const API_URL = process.env.REACT_APP_API_URL || 'http://localhost:8000';

// Provider component
export const AuthProvider = ({ children }) => {
  const [user, setUser] = useState(null);
  const [isAuthenticated, setIsAuthenticated] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  // Initialize auth state from localStorage on component mount
  useEffect(() => {
    const initAuth = async () => {
      const accessToken = localStorage.getItem('accessToken');
      const refreshToken = localStorage.getItem('refreshToken');
      
      if (!accessToken || !refreshToken) {
        setLoading(false);
        return;
      }
      
      try {
        // Check if token is expired
        const decodedToken = jwtDecode(accessToken);
        const currentTime = Date.now() / 1000;
        
        if (decodedToken.exp < currentTime) {
          // Token is expired, try to refresh
          await refreshAccessToken();
        } else {
          // Token is valid, fetch user info
          await fetchUserInfo(accessToken);
        }
      } catch (err) {
        console.error('Auth initialization error:', err);
        logout();
      } finally {
        setLoading(false);
      }
    };
    
    initAuth();
  }, []);

  // Fetch user info using the access token
  const fetchUserInfo = async (token) => {
    try {
      const response = await axios.get(`${API_URL}/auth/me`, {
        headers: { Authorization: `Bearer ${token}` }
      });
      
      setUser(response.data);
      setIsAuthenticated(true);
    } catch (err) {
      console.error('Error fetching user info:', err);
      setError('Failed to fetch user information');
      logout();
    }
  };

  // Login function
  const login = async (username, password) => {
    try {
      setLoading(true);
      setError(null);
      
      const response = await axios.post(`${API_URL}/auth/login`, {
        username,
        password
      }, {
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' }
      });
      
      const { access_token, refresh_token } = response.data;
      
      // Store tokens in localStorage
      localStorage.setItem('accessToken', access_token);
      localStorage.setItem('refreshToken', refresh_token);
      
      // Fetch user info
      await fetchUserInfo(access_token);
      
      return true;
    } catch (err) {
      console.error('Login error:', err);
      setError(err.response?.data?.detail || 'Login failed');
      return false;
    } finally {
      setLoading(false);
    }
  };

  // Signup function
  const signup = async (username, email, password) => {
    try {
      setLoading(true);
      setError(null);
      
      await axios.post(`${API_URL}/auth/signup`, {
        username,
        email,
        password
      });
      
      // Automatically log in after successful signup
      return await login(username, password);
    } catch (err) {
      console.error('Signup error:', err);
      setError(err.response?.data?.detail || 'Signup failed');
      return false;
    } finally {
      setLoading(false);
    }
  };

  // Refresh token function
  const refreshAccessToken = async () => {
    try {
      const refreshToken = localStorage.getItem('refreshToken');
      
      if (!refreshToken) {
        throw new Error('No refresh token available');
      }
      
      const response = await axios.post(`${API_URL}/auth/refresh`, {
        refresh_token: refreshToken
      });
      
      const { access_token, refresh_token } = response.data;
      
      // Update tokens in localStorage
      localStorage.setItem('accessToken', access_token);
      localStorage.setItem('refreshToken', refresh_token);
      
      // Fetch user info with new token
      await fetchUserInfo(access_token);
      
      return true;
    } catch (err) {
      console.error('Token refresh error:', err);
      logout();
      return false;
    }
  };

  // Logout function
  const logout = () => {
    // Clear tokens from localStorage
    localStorage.removeItem('accessToken');
    localStorage.removeItem('refreshToken');
    
    // Reset state
    setUser(null);
    setIsAuthenticated(false);
    setError(null);
  };

  // Create axios instance with auth headers
  const authAxios = axios.create();
  
  // Add request interceptor to add auth header
  authAxios.interceptors.request.use(
    (config) => {
      const token = localStorage.getItem('accessToken');
      if (token) {
        config.headers.Authorization = `Bearer ${token}`;
      }
      return config;
    },
    (error) => Promise.reject(error)
  );
  
  // Add response interceptor to handle token refresh
  authAxios.interceptors.response.use(
    (response) => response,
    async (error) => {
      const originalRequest = error.config;
      
      // If error is 401 and we haven't tried to refresh the token yet
      if (error.response?.status === 401 && !originalRequest._retry) {
        originalRequest._retry = true;
        
        try {
          // Try to refresh the token
          const refreshed = await refreshAccessToken();
          
          if (refreshed) {
            // Retry the original request with new token
            const token = localStorage.getItem('accessToken');
            originalRequest.headers.Authorization = `Bearer ${token}`;
            return axios(originalRequest);
          }
        } catch (refreshError) {
          console.error('Error refreshing token:', refreshError);
          return Promise.reject(refreshError);
        }
      }
      
      return Promise.reject(error);
    }
  );

  // Context value
  const value = {
    user,
    isAuthenticated,
    loading,
    error,
    login,
    signup,
    logout,
    refreshAccessToken,
    authAxios
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
};

// Custom hook to use the auth context
export const useAuth = () => {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
};