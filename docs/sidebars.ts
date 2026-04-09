import type {SidebarsConfig} from '@docusaurus/plugin-content-docs';

const sidebars: SidebarsConfig = {
  mcpSidebar: [
    'readme',
    {
      type: 'category',
      label: 'Guides',
      items: [
        'guides/installation',
        'guides/docker',
        'guides/authentication',
      ],
    },
    {
      type: 'category',
      label: 'Reference',
      items: [
        'references/configuration',
        'references/methods',
      ],
    },
  ]
};

export default sidebars;
