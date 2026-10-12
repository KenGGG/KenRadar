/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 */

import React from 'react';
import { ThemeProvider } from './hooks/useTheme';
import AppContent from './AppContent';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
const queryClient = new QueryClient();

export default function App() {
  return (
    <QueryClientProvider client={queryClient}><ThemeProvider>
      <AppContent />
    </ThemeProvider></QueryClientProvider>
  );
}
