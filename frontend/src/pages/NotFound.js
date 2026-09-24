import React from 'react';
import { Link } from 'react-router-dom';

const NotFound = () => (
  <div className="flex flex-col items-center justify-center min-h-screen bg-gray-50 px-4">
    <p className="text-6xl font-bold text-blue-600">404</p>
    <h1 className="mt-4 text-2xl font-semibold text-gray-900">Page not found</h1>
    <p className="mt-2 text-gray-600">
      The page you are looking for does not exist or has been moved.
    </p>
    <Link
      to="/"
      className="mt-6 rounded-md bg-blue-600 px-4 py-2 text-white hover:bg-blue-700"
    >
      Back to dashboard
    </Link>
  </div>
);

export default NotFound;
