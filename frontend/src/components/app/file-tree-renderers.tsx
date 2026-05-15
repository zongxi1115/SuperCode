import { FileTreeFile, FileTreeFolder } from '@/components/ai-elements/file-tree';
import type { DirectoryNode, FileTreeNode } from '@/lib/app-types';

export function renderFileTreeNodes(nodes: FileTreeNode[]): JSX.Element[] {
  return nodes.map((node) =>
    node.type === 'folder' ? (
      <FileTreeFolder key={node.path} path={node.path} name={node.name}>
        {renderFileTreeNodes(node.children ?? [])}
      </FileTreeFolder>
    ) : (
      <FileTreeFile key={node.path} path={node.path} name={node.name} />
    )
  );
}

export function renderDirectoryNodes(nodes: DirectoryNode[]): JSX.Element[] {
  return nodes.map((node) => (
    <FileTreeFolder key={node.path} path={node.path} name={node.name}>
      {renderDirectoryNodes(node.children ?? [])}
    </FileTreeFolder>
  ));
}
