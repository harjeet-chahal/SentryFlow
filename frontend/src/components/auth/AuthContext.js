import React, { createContext, useState, useContext, useEffect, useCallback, useMemo, useRef } from 'react';
import axios from 'axios';
import jwtDecode from 'jwt-decode';

// Create context
const AuthContext = createContext();

// API URL. `??` rather than `||` so that building with REACT_APP_API_URL=""
// produces same-origin relative URLs (production serves the API behind the
// same host as the dashboard).
export const API_URL = process.env.REACT_APP_API_URL ?? 'http://localhost:8000';

// Absolute URL of a gateway path, for display (e.g. curl examples).
export const publicApiUrl = (path = '') => `${API_URL || window.location.origin}${path}`;

// Provider component
export const AuthProvider = ({ children }) => {
  const [user, setUser] = useState(null);
  const [isAuthenticated, setIsAuthenticated] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  // One in-flight token refresh shared by every request that got a 401.
  const refreshPromiseRef = useRef(null);

  // Logout function
  const logout = useCallback(() => {
    // Clear tokens from localStorage
    localStorage.removeItem('accessToken');
    localStorage.removeItem('refreshToken');

    // Reset state
    setUser(null);
    setIsAuthenticated(false);
    setError(null);
  }, []);

  // Fetch user info using the access token. Resolves to true on success.
  const fetchUserInfo = useCallback(
    async (token) => {
      try {
        const response = await axios.get(`${API_URL}/auth/me`, {
          headers: { Authorization: `Bearer ${token}` },
        });

        setUser(response.data);
        setIsAuthenticated(true);
        return true;
      } catch (err) {
        console.error('Error fetching user info:', err);
        logout();
        setError('Failed to fetch user information');
        return false;
      }
    },
    [logout]
  );

  // Refresh token function. Resolves to true when a new token pair is stored.
  const refreshAccessToken = useCallback(() => {
    if (!refreshPromiseRef.current) {
      const doRefresh = async () => {
        try {
          const refreshToken = localStorage.getItem('refreshToken');

          if (!refreshToken) {
            throw new Error('No refresh token available');
          }

          const response = await axios.post(`${API_URL}/auth/refresh`, {
            refresh_token: refreshToken,
          });

          const { access_token, refresh_token } = response.data;

          // Update tokens in localStorage
          localStorage.setItem('accessToken', access_token);
          localStorage.setItem('refreshToken', refresh_token);

          // Fetch user info with new token
          return await fetchUserInfo(access_token);
        } catch (err) {
          console.error('Token refresh error:', err);
          logout();
          return false;
        }
      };
      refreshPromiseRef.current = doRefresh().finally(() => {
        refreshPromiseRef.current = null;
      });
    }
    return refreshPromiseRef.current;
  }, [fetchUserInfo, logout]);

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
  }, [fetchUserInfo, logout, refreshAccessToken]);

  // Login function
  const login = useCallback(
    async (username, password) => {
      try {
        setLoading(true);
        setError(null);

        const response = await axios.post(
          `${API_URL}/auth/login`,
          {
            username,
            password,
          },
          {
            headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
          }
        );

        const { access_token, refresh_token } = response.data;

        // Store tokens in localStorage
        localStorage.setItem('accessToken', access_token);
        localStorage.setItem('refreshToken', refresh_token);

        // Fetch user info
        return await fetchUserInfo(access_token);
      } catch (err) {
        console.error('Login error:', err);
        setError(err.response?.data?.detail || 'Login failed');
        return false;
      } finally {
        setLoading(false);
      }
    },
    [fetchUserInfo]
  );

  // Signup function
  const signup = useCallback(
    async (username, email, password) => {
      try {
        setLoading(true);
        setError(null);

        await axios.post(`${API_URL}/auth/signup`, {
          username,
          email,
          password,
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
    },
    [login]
  );

  // Axios instance for authenticated API calls. Created once so that pages
  // can safely list it as an effect dependency.
  const authAxios = useMemo(() => {
    const instance = axios.create({ baseURL: API_URL });

    // Add the current access token to every request
    instance.interceptors.request.use(
      (config) => {
        const token = localStorage.getItem('accessToken');
        if (token) {
          config.headers.Authorization = `Bearer ${token}`;
        }
        return config;
      },
      (err) => Promise.reject(err)
    );

    // On a 401, refresh the token once and retry the request
    instance.interceptors.response.use(
      (response) => response,
      async (err) => {
        const originalRequest = err.config;

        if (err.response?.status === 401 && originalRequest && !originalRequest._retry) {
          originalRequest._retry = true;

          const refreshed = await refreshAccessToken();
          if (refreshed) {
            // Retry through this instance: keeps the baseURL, and the request
            // interceptor attaches the new token.
            return instance(originalRequest);
          }
        }

        return Promise.reject(err);
      }
    );

    return instance;
  }, [refreshAccessToken]);

  // Context value
  const value = useMemo(
    () => ({
      user,
      isAdmin: Boolean(user?.is_admin),
      isAuthenticated,
      loading,
      error,
      login,
      signup,
      logout,
      refreshAccessToken,
      authAxios,
    }),
    [user, isAuthenticated, loading, error, login, signup, logout, refreshAccessToken, authAxios]
  );

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
