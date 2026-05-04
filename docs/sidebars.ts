import type {SidebarsConfig} from '@docusaurus/plugin-content-docs';

const sidebars: SidebarsConfig = {
  mcpSidebar: [
    'readme',
    {
      type: 'category',
      label: 'Getting started',
      items: [
        'getting-started/installation',
        'getting-started/authentication',
        'getting-started/first-agent-run',
        'getting-started/make-a-change',
      ],
    },
    {
      type: 'category',
      label: 'Deployment',
      items: [
        'guides/docker-compose',
      ],
    },
    {
      type: 'category',
      label: 'Use cases',
      items: [
        'use-cases/troubleshooting-queries',
        'use-cases/natural-language-graphql',
        'use-cases/cross-system-correlation',
        'use-cases/compliance-analysis',
        'use-cases/brownfield-onboarding',
        'use-cases/safe-changes-branch-isolation',
      ],
    },
    {
      type: 'category',
      label: 'Integrations',
      items: [
        'integrations/claude-desktop',
        'integrations/claude-code',
        'integrations/cursor',
        'integrations/vscode',
        'integrations/openai-agents-sdk',
        'integrations/claude-agent-sdk',
      ],
    },
    {
      type: 'category',
      label: 'Reference',
      items: [
        'references/authentication',
        'references/configuration',
        'references/methods',
      ],
    },
  ]
};

export default sidebars;
