import React, { useState, useEffect } from 'react';
import { useAuth } from '../components/auth/AuthContext';
import { format } from 'date-fns';

const ApiKeys = () => {
  const { authAxios } = useAuth();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [apiKeys, setApiKeys] = useState([]);
  const [newKeyName, setNewKeyName] = useState('');
  const [showNewKey, setShowNewKey] = useState(null);
  const [createKeyError, setCreateKeyError] = useState(null);
  
  // Fetch API keys
  useEffect(() => {
    const fetchApiKeys = async () => {
      try {
        setLoading(true);
        setError(null);
        
        // In a real app, this would be an actual API call
        // const response = await authAxios.get('/auth/apikeys');
        // setApiKeys(response.data);
        
        // For demo purposes, we'll use mock data
        const mockApiKeys = [
          {
            id: '1',
            key: 'sk_test_51JKj7rLkjhgfdsa987654321qwerty',
            name: 'Production API Key',
            created_at: new Date(Date.now() - 30 * 24 * 60 * 60 * 1000), // 30 days ago
            last_used_at: new Date(Date.now() - 2 * 60 * 60 * 1000), // 2 hours ago
            is_active: true
          },
          {
            id: '2',
            key: 'sk_test_51JKj7rPoiuytrewq123456789asdfgh',
            name: 'Development API Key',
            created_at: new Date(Date.now() - 15 * 24 * 60 * 60 * 1000), // 15 days ago
            last_used_at: new Date(Date.now() - 5 * 24 * 60 * 60 * 1000), // 5 days ago
            is_active: true
          },
          {
            id: '3',
            key: 'sk_test_51JKj7rZxcvbnmlkjhgfdsaqwertyui',
            name: 'Testing API Key',
            created_at: new Date(Date.now() - 60 * 24 * 60 * 60 * 1000), // 60 days ago
            last_used_at: null,
            is_active: false
          }
        ];
        
        setApiKeys(mockApiKeys);
      } catch (err) {
        console.error('Error fetching API keys:', err);
        setError('Failed to load API keys');
      } finally {
        setLoading(false);
      }
    };
    
    fetchApiKeys();
  }, [authAxios]);
  
  // Create new API key
  const handleCreateKey = async (e) => {
    e.preventDefault();
    
    if (!newKeyName.trim()) {
      setCreateKeyError('API key name is required');
      return;
    }
    
    try {
      setCreateKeyError(null);
      
      // In a real app, this would be an actual API call
      // const response = await authAxios.post('/auth/apikeys/create', { name: newKeyName });
      // const newKey = response.data;
      
      // For demo purposes, we'll create a mock key
      const newKey = {
        id: `${apiKeys.length + 1}`,
        key: `sk_test_${Math.random().toString(36).substring(2, 15)}${Math.random().toString(36).substring(2, 15)}`,
        name: newKeyName,
        created_at: new Date(),
        last_used_at: null,
        is_active: true
      };
      
      // Show the new key to the user (only shown once)
      setShowNewKey(newKey);
      
      // Add to the list
      setApiKeys([newKey, ...apiKeys]);
      
      // Clear the form
      setNewKeyName('');
    } catch (err) {
      console.error('Error creating API key:', err);
      setCreateKeyError('Failed to create API key');
    }
  };
  
  // Toggle API key status (active/inactive)
  const handleToggleKeyStatus = async (keyId) => {
    try {
      // Find the key to toggle
      const keyIndex = apiKeys.findIndex(key => key.id === keyId);
      if (keyIndex === -1) return;
      
      // In a real app, this would be an actual API call
      // await authAxios.put(`/auth/apikeys/${keyId}/toggle`);
      
      // Update the local state
      const updatedKeys = [...apiKeys];
      updatedKeys[keyIndex] = {
        ...updatedKeys[keyIndex],
        is_active: !updatedKeys[keyIndex].is_active
      };
      
      setApiKeys(updatedKeys);
    } catch (err) {
      console.error('Error toggling API key status:', err);
      setError('Failed to update API key');
    }
  };
  
  // Format date for display
  const formatDate = (date) => {
    if (!date) return 'Never';
    return format(new Date(date), 'MMM d, yyyy h:mm a');
  };
  
  // Mask API key for display
  const maskApiKey = (key) => {
    if (!key) return '';
    return `${key.substring(0, 8)}...${key.substring(key.length - 4)}`;
  };
  
  if (loading) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="animate-spin rounded-full h-12 w-12 border-t-2 border-b-2 border-blue-500"></div>
      </div>
    );
  }
  
  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold text-gray-900">API Keys</h1>
      </div>
      
      {/* Create new API key form */}
      <div className="bg-white shadow rounded-lg p-6">
        <h2 className="text-lg font-medium text-gray-900 mb-4">Create New API Key</h2>
        
        {createKeyError && (
          <div className="mb-4 rounded-md bg-red-50 p-4">
            <div className="flex">
              <div className="ml-3">
                <h3 className="text-sm font-medium text-red-800">{createKeyError}</h3>
              </div>
            </div>
          </div>
        )}
        
        {showNewKey && (
          <div className="mb-4 rounded-md bg-green-50 p-4">
            <div className="flex">
              <div className="ml-3">
                <h3 className="text-sm font-medium text-green-800">API Key Created Successfully</h3>
                <div className="mt-2 text-sm text-green-700">
                  <p>Your new API key: <span className="font-mono">{showNewKey.key}</span></p>
                  <p className="mt-1 text-xs text-red-600 font-semibold">This is the only time you'll see this key. Please copy it now.</p>
                </div>
                <div className="mt-4">
                  <button
                    type="button"
                    className="text-sm font-medium text-green-800 hover:text-green-700"
                    onClick={() => setShowNewKey(null)}
                  >
                    Dismiss
                  </button>
                </div>
              </div>
            </div>
          </div>
        )}
        
        <form onSubmit={handleCreateKey} className="space-y-4">
          <div>
            <label htmlFor="key-name" className="block text-sm font-medium text-gray-700">Key Name</label>
            <input
              type="text"
              id="key-name"
              className="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 sm:text-sm"
              placeholder="e.g., Production API Key"
              value={newKeyName}
              onChange={(e) => setNewKeyName(e.target.value)}
            />
          </div>
          
          <div>
            <button
              type="submit"
              className="inline-flex items-center px-4 py-2 border border-transparent text-sm font-medium rounded-md shadow-sm text-white bg-blue-600 hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500"
            >
              Create API Key
            </button>
          </div>
        </form>
      </div>
      
      {/* API keys list */}
      <div className="bg-white shadow rounded-lg overflow-hidden">
        <div className="px-4 py-5 sm:px-6">
          <h2 className="text-lg font-medium text-gray-900">Your API Keys</h2>
          <p className="mt-1 text-sm text-gray-500">Manage your existing API keys</p>
        </div>
        
        {error && (
          <div className="mx-4 mb-4 rounded-md bg-red-50 p-4">
            <div className="flex">
              <div className="ml-3">
                <h3 className="text-sm font-medium text-red-800">{error}</h3>
              </div>
            </div>
          </div>
        )}
        
        <div className="border-t border-gray-200 px-4 py-5 sm:p-0">
          <dl className="sm:divide-y sm:divide-gray-200">
            {apiKeys.length === 0 ? (
              <div className="py-4 sm:py-5 sm:grid sm:grid-cols-3 sm:gap-4 sm:px-6">
                <dt className="text-sm font-medium text-gray-500">No API keys found</dt>
                <dd className="mt-1 text-sm text-gray-900 sm:mt-0 sm:col-span-2">
                  Create your first API key using the form above.
                </dd>
              </div>
            ) : (
              apiKeys.map((key) => (
                <div key={key.id} className="py-4 sm:py-5 sm:grid sm:grid-cols-3 sm:gap-4 sm:px-6">
                  <dt className="text-sm font-medium text-gray-500">
                    <div className="font-semibold">{key.name}</div>
                    <div className="mt-1 text-xs text-gray-400">
                      Created: {formatDate(key.created_at)}
                    </div>
                  </dt>
                  <dd className="mt-1 text-sm text-gray-900 sm:mt-0 sm:col-span-2">
                    <div className="flex justify-between">
                      <div>
                        <div className="font-mono">{maskApiKey(key.key)}</div>
                        <div className="mt-1 text-xs text-gray-500">
                          Last used: {formatDate(key.last_used_at)}
                        </div>
                      </div>
                      <div className="flex items-center">
                        <span
                          className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${
                            key.is_active
                              ? 'bg-green-100 text-green-800'
                              : 'bg-red-100 text-red-800'
                          }`}
                        >
                          {key.is_active ? 'Active' : 'Inactive'}
                        </span>
                        <button
                          type="button"
                          onClick={() => handleToggleKeyStatus(key.id)}
                          className="ml-4 text-sm font-medium text-blue-600 hover:text-blue-500"
                        >
                          {key.is_active ? 'Deactivate' : 'Activate'}
                        </button>
                      </div>
                    </div>
                  </dd>
                </div>
              ))
            )}
          </dl>
        </div>
      </div>
    </div>
  );
};

export default ApiKeys;