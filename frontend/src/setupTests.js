// jest-dom adds custom jest matchers for asserting on DOM nodes,
// e.g. expect(element).toBeInTheDocument().
import '@testing-library/jest-dom';

// @testing-library/react 13 still calls ReactDOMTestUtils.act, which React
// 18.3 reports as deprecated on every render. Drop just that message.
// (A plain wrapper, not jest.spyOn: CRA's resetMocks would reset a spy.)
const originalConsoleError = console.error;
console.error = (...args) => {
  if (typeof args[0] === 'string' && args[0].includes('ReactDOMTestUtils.act')) return;
  originalConsoleError(...args);
};
