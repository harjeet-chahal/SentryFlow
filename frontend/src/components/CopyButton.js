import React, { useEffect, useState } from 'react';

// navigator.clipboard needs a secure context (https or localhost); fall back
// to a hidden textarea + execCommand for plain-http deployments.
export async function copyText(text) {
  if (navigator.clipboard && window.isSecureContext) {
    await navigator.clipboard.writeText(text);
    return;
  }
  const textarea = document.createElement('textarea');
  textarea.value = text;
  textarea.setAttribute('readonly', '');
  textarea.style.position = 'fixed';
  textarea.style.opacity = '0';
  document.body.appendChild(textarea);
  textarea.select();
  try {
    const ok = typeof document.execCommand === 'function' && document.execCommand('copy');
    if (!ok) throw new Error('Copy command was rejected');
  } finally {
    document.body.removeChild(textarea);
  }
}

const CopyButton = ({ text, label = 'Copy', className = '' }) => {
  const [status, setStatus] = useState(null); // null | 'copied' | 'failed'

  useEffect(() => {
    if (!status) return undefined;
    const timer = setTimeout(() => setStatus(null), 2000);
    return () => clearTimeout(timer);
  }, [status]);

  const handleClick = async () => {
    try {
      await copyText(text);
      setStatus('copied');
    } catch (err) {
      setStatus('failed');
    }
  };

  return (
    <button
      type="button"
      onClick={handleClick}
      className={`text-sm font-medium text-blue-600 hover:text-blue-500 ${className}`}
    >
      {status === 'copied' ? 'Copied!' : status === 'failed' ? 'Copy failed' : label}
    </button>
  );
};

export default CopyButton;
