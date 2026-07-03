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
    {
      type: 'category',
      label: 'Release Notes',
      collapsible: true,
      collapsed: true,
      link: {
        type: 'generated-index',
        slug: 'release-notes',
      },
      items: [
        'release-notes/release-1_1_7',
        'release-notes/release-1_1_6',
        'release-notes/release-1_1_5',
        'release-notes/release-1_1_4',
        'release-notes/release-1_1_3',
        'release-notes/release-1_1_2',
        'release-notes/release-1_1_1',
        'release-notes/release-1_0_1',
        'release-notes/release-1_0_0',
      ],
    },
  ]
};

export default sidebars;
